"""The baseline conversational-BI agent.

A manual tool-use loop (rather than a framework's agent runner) so that every message and
tool result is visible in `AgentResult.transcript` — the eval harness reads it to decide
whether restricted data reached the model's context.
"""

import json
import logging
import threading
from dataclasses import dataclass, field

import openai

from . import db, disclosure, policy, tools

log = logging.getLogger("agent.baseline")

MODEL = "gpt-5.5"
MAX_TOKENS = 12000
MAX_TURNS = 12

SYSTEM = """You are the analytics assistant for a bank's fraud operations team. \
Users ask questions in plain language; you answer them from the warehouse.

You are currently acting on behalf of:
  user_id: {user_id}
  name:    {full_name}
  role:    {role}
  region:  {region}

What this user can see. The server enforces this on every query, whatever SQL you write:
{access}

If answering needs data outside this access, call decline and say that access is the
reason. Do not try to query tables or columns that are not available. A run_sql result
starting with "access denied:" is a refusal: call decline with that reason. One starting
with "unsupported:" means the query shape could not be checked, so rewrite it as the
message says, or decline.

Data notes:
- Customers with a non-null deleted_at have been offboarded and are not current customers.
- transactions.amount_minor is in minor units (cents, centavos) of transactions.currency.
  USD, EUR and MXN all appear and there is no FX table, so never add amounts in different
  currencies together and never convert between them. When a question names a currency
  ("in dollars", "US dollar"), filter to it and answer. When it asks for one money total
  without naming a currency, query first: if the rows are all one currency, answer. If they
  mix currencies, ask whether they want it per currency or for one currency.
- "Volume" can mean a number of transactions or a sum of amounts. Ask which.
- alerts.status is open, closed or resolved. A word that names one of those maps to it.
  Any other word, like outstanding, pending or unresolved, could mean open alone or open
  plus resolved, so ask which statuses count.
- Timestamps are UTC. The warehouse has no notion of today, so relative dates like
  yesterday, last week or this month are ambiguous. Ask for the dates.

When a question is ambiguous, call ask_clarifying_question. When it cannot be answered from
this schema, call decline. If any part of a question can't be answered at all, decline
instead of asking about the rest. Answer concisely and state the number plainly."""

# keyed by scope fingerprint and conversation id so follow-ups keep their context
# a different user, or the same user after a role or region change, never sees it
_HISTORY: dict[tuple[str, str], list[dict]] = {}
# conversation id and the fingerprint of the scope that started it
_OWNER: dict[str, str] = {}
_LOCK = threading.Lock()


@dataclass
class AgentResult:
    answer: str = ""
    transcript: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    sql_log: list[str] = field(default_factory=list)
    clarified: bool = False
    declined: bool = False
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    # set when the conversation id belonged to another identity or older permissions
    context_reset: str | None = None
    # the server's refusal, when the turn ended on one
    refusal: str | None = None

    def called(self, name: str) -> bool:
        return any(c["name"] == name for c in self.tool_calls)


def run(question: str, user_id: str, conversation_id: str | None = None) -> AgentResult:
    client = openai.OpenAI()
    # identity and scope come from the session, never from the model
    scope = policy.scope_for(db.get_user(user_id))
    result = AgentResult()

    system = SYSTEM.format(
        user_id=scope.user_id,
        full_name=scope.full_name,
        role=scope.role,
        region=scope.region or "(all regions)",
        access=policy.prompt_access(scope),
    )

    history_key = (policy.fingerprint(scope), conversation_id)
    messages = None
    if conversation_id:
        with _LOCK:
            if history_key in _HISTORY:
                messages = list(_HISTORY[history_key])
            elif _OWNER.get(conversation_id, history_key[0]) != history_key[0]:
                result.context_reset = (
                    "this conversation was started by another identity or under different "
                    "permissions, so it starts fresh"
                )
            _OWNER.setdefault(conversation_id, history_key[0])
    if messages is None:
        messages = [{"role": "system", "content": system}]
    messages.append({"role": "user", "content": question})
    result.transcript.append(f"[user] {question}")

    # the most recent run_sql refusal, cleared by any later run_sql that wasn't refused
    last_refusal: str | None = None
    for _ in range(MAX_TURNS):
        result.turns += 1
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_completion_tokens=MAX_TOKENS,
                tools=tools.TOOLS,
                messages=messages,
            )
        except openai.APIError as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        if response.usage:
            result.input_tokens += response.usage.prompt_tokens
            result.output_tokens += response.usage.completion_tokens

        message = response.choices[0].message

        if getattr(message, "refusal", None):
            result.error = "model refused"
            return result

        if message.content and message.content.strip():
            result.transcript.append(f"[assistant] {message.content}")

        assistant_msg: dict = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in message.tool_calls
            ]
        messages.append(assistant_msg)

        if not message.tool_calls:
            result.answer = (message.content or "").strip()
            # the server refused and the model wrapped it in prose instead of calling decline
            # the refusal stands, it comes from the server not from the model's choice of tool
            if last_refusal:
                result.declined = True
                result.refusal = last_refusal
            break

        terminal = False
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": "error: arguments were not valid JSON",
                })
                continue

            result.tool_calls.append({"name": name, "input": args})
            result.transcript.append(f"[tool_use {name}] {json.dumps(args)}")

            if name == "run_sql":
                result.sql_log.append(args.get("sql", ""))

            output = tools.dispatch(name, args, scope=scope)
            result.transcript.append(f"[tool_result {name}] {output}")
            if name == "run_sql":
                last_refusal = output if output.startswith(tools.REFUSAL_PREFIXES) else None
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": output}
            )

            if name in tools.TERMINAL_TOOLS:
                terminal = True
                result.answer = output
                result.clarified = result.clarified or name == "ask_clarifying_question"
                result.declined = result.declined or name == "decline"

        if terminal:
            break

    if conversation_id:
        with _LOCK:
            _HISTORY[history_key] = messages

    return result


def reset_state() -> None:
    """Clear conversation history between eval runs."""
    with _LOCK:
        _HISTORY.clear()
        _OWNER.clear()
    disclosure.reset_audit()
