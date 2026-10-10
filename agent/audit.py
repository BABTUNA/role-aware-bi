"""per-turn audit records, the answer to "what did the agent see, on whose authority"

the full record is appended server-side as one JSON line per turn to AUDIT_PATH
it holds the identity, the resolved permissions and the SQL that applies them, every tool call
with exactly what the model was shown, the floor checks and redactions, and the outcome
what the model was shown is customer data, so the file is as sensitive as the warehouse
it never holds data the user wasn't shown, the people behind a floor check are kept as counts

AgentResult.audit gets sanitize(record) instead, the parts of the turn the user may see
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from . import policy

AUDIT_PATH = os.environ.get(
    "AUDIT_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit.jsonl"),
)
_LOCK = threading.Lock()


class AuditWriteError(Exception):
    """the record could not be written, the turn's answer is withheld"""


def authority(scope: policy.Scope) -> dict:
    """the resolved permissions a turn ran under, including the SQL that applies them"""
    p = scope.policy
    return {
        "policy_fingerprint": policy.fingerprint(scope),
        "tables": list(p.tables),
        "schema_only": list(p.schema_only),
        "rows": policy.row_scope(scope),
        "customer_columns": list(p.customer_columns),
        "withheld_columns": policy.hidden_columns(scope) if "customers" in p.tables else [],
        "aggregate_only": p.aggregate_only,
        "views": policy.views(scope),
    }


class Turn:
    """collects one turn's record as the agent loop runs"""

    def __init__(self, scope: policy.Scope, question: str, conversation_id: str | None):
        self.started = time.monotonic()
        self.record = {
            "turn_id": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "conversation_id": conversation_id,
            "identity": {
                "user_id": scope.user_id,
                "full_name": scope.full_name,
                "role": scope.role,
                "region": scope.region,
            },
            "authority": authority(scope),
            "question": question,
            "steps": [],
        }

    def step(self, name: str, args: dict | None, output: str, trace: dict) -> None:
        step = {"tool": name, "status": trace.get("status", "ok")}
        if name == "run_sql":
            step.update(
                sql=(args or {}).get("sql"),
                reason=trace.get("reason"),
                columns=trace.get("columns", []),
                rows=trace.get("rows", []),
                row_count=trace.get("row_count", 0),
                truncated=trace.get("truncated", False),
                redactions=trace.get("redactions", []),
                floor_checks=trace.get("checks", []),
                duration_ms=trace.get("duration_ms"),
            )
        elif name == "make_chart":
            # the plotted rows are already in model_saw, keep the encoding readable here
            args = args or {}
            step["args"] = {k: args.get(k) for k in ("mark", "x_field", "y_field", "title")}
            step["row_count"] = len(args.get("rows") or [])
        else:
            step["args"] = args
        # the exact text that entered the model's context
        step["model_saw"] = output
        self.record["steps"].append(step)

    def finish(self, result, model: str) -> dict:
        if result.error:
            status = "error"
        elif result.declined:
            status = "declined"
        elif result.clarified:
            status = "clarified"
        elif result.answer:
            status = "answered"
        else:
            status = "no_answer"
        self.record["outcome"] = {
            "status": status,
            "answer": result.answer,
            "refusal": result.refusal,
            "error": result.error,
            "context_reset": result.context_reset,
        }
        self.record["model"] = model
        self.record["tokens"] = {"input": result.input_tokens, "output": result.output_tokens}
        self.record["model_calls"] = result.turns
        self.record["latency_ms"] = round((time.monotonic() - self.started) * 1000)
        return self.record


def write(record: dict) -> None:
    """append one record, the file is created readable by its owner only"""
    line = json.dumps(record, default=str, ensure_ascii=False)
    try:
        with _LOCK:
            fd = os.open(AUDIT_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError as exc:
        raise AuditWriteError(str(exc)) from exc


# fields of a run_sql step the user may see, everything else stays server-side
_USER_STEP_FIELDS = ("sql", "status", "reason", "columns", "rows", "row_count", "truncated", "redactions")


def sanitize(record: dict) -> dict:
    """the user's own view of a turn, for the frontend

    keeps what they asked, under which scope, the queries run for them and the rows they were
    shown, and the outcome
    drops the view SQL, the policy fingerprint, floor-check queries and their counts, and the raw
    tool text
    """
    steps = []
    for s in record["steps"]:
        out = {"tool": s["tool"], "status": s["status"]}
        if s["tool"] == "run_sql":
            out.update({k: s.get(k) for k in _USER_STEP_FIELDS})
        elif s["tool"] == "describe_table":
            out["table"] = (s.get("args") or {}).get("table")
        elif "args" in s:
            out["args"] = s["args"]
        steps.append(out)
    scope = {k: v for k, v in record["authority"].items() if k not in ("views", "policy_fingerprint")}
    return {
        "turn_id": record["turn_id"],
        "ts": record["ts"],
        "conversation_id": record["conversation_id"],
        "identity": record["identity"],
        "scope": scope,
        "question": record["question"],
        "steps": steps,
        "outcome": record["outcome"],
        "latency_ms": record.get("latency_ms"),
        "tokens": record.get("tokens"),
    }
