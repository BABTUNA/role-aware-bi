"""Tool definitions and dispatch for the baseline agent.

This is the layer between the model and the data. Read it closely.
"""

import logging
import time

from . import charts, db, policy

log = logging.getLogger("agent.tools")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List the tables available in the warehouse.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": "Return the CREATE TABLE statement for one table.",
            "parameters": {
                "type": "object",
                "properties": {"table": {"type": "string"}},
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Run a read-only SQL query against the warehouse and return the rows. "
                "The server applies the signed-in user's access scope to every query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A single SELECT statement."},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_chart",
            "description": (
                "Chart the result of the most recent successful run_sql in this turn. "
                "The server builds the chart from that result, so run the query first in "
                "the same turn and name two of its columns. Don't pass any data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mark": {"type": "string", "enum": ["bar", "line", "point"]},
                    "x_field": {"type": "string", "description": "A column of the last result."},
                    "y_field": {"type": "string", "description": "A numeric column of the last result."},
                    "title": {"type": "string"},
                },
                "required": ["mark", "x_field", "y_field"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarifying_question",
            "description": (
                "Use when the question is ambiguous and different readings would produce "
                "materially different answers. Ends the turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decline",
            "description": (
                "Use when the question cannot or must not be answered — the data does "
                "not exist, or answering would exceed what this user is allowed to see. "
                "Ends the turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "because": {
                        "type": "string",
                        "enum": ["access", "unavailable"],
                        "description": (
                            "access when the user's permissions are the reason, unavailable when "
                            "the data doesn't exist or can't be computed. Shown to the user as a label."
                        ),
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

TERMINAL_TOOLS = {"ask_clarifying_question", "decline"}

# run_sql results that are a refusal from the server rather than data or an error
REFUSAL_PREFIXES = ("access denied:", "unsupported:")


def _run_sql(sql: str, scope: policy.Scope, trace: dict) -> str:
    """trace collects the structured outcome for the audit record"""
    trace["checks"] = []
    started = time.monotonic()
    try:
        result = db.query(sql, scope, trace["checks"])
    except db.AccessDenied as exc:
        log.info("user=%s denied sql=%s reason=%s", scope.user_id, sql, exc)
        trace.update(status="access_denied", reason=str(exc))
        return f"access denied: {exc}"
    except db.Unsupported as exc:
        log.info("user=%s unsupported sql=%s reason=%s", scope.user_id, sql, exc)
        trace.update(status="unsupported", reason=str(exc))
        return f"unsupported: {exc}"
    except db.SQLError as exc:
        trace.update(status="error", reason=str(exc))
        return f"error: {exc}"
    finally:
        trace["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    rows = result.rows
    log.info("user=%s sql=%s rows=%d", scope.user_id, sql, len(rows))
    trace.update(
        status="ok",
        columns=list(result.columns),
        rows=[list(r.values()) for r in rows],
        row_count=len(rows),
        truncated=result.truncated,
        redactions=list(result.redactions),
    )

    notes = []
    if result.truncated:
        notes.append(f"truncated: only the first {db.MAX_ROWS} rows are shown, more matched")
    notes += [f"redacted: {r}" for r in result.redactions]
    # tells the model a zero or a short list may be the scope, not the data
    if policy.row_scope(scope):
        notes.append(f"scope: {policy.row_scope(scope)}")
    tail = "".join(f"\n{n}" for n in notes)
    if not rows:
        return "0 rows" + tail
    header = " | ".join(rows[0].keys())
    body = "\n".join(" | ".join(str(v) for v in r.values()) for r in rows)
    return f"{len(rows)} row(s)\n{header}\n{body}{tail}"


def _describe_table(table: str, scope: policy.Scope) -> str:
    create_sql = db.table_sql(table)
    if create_sql is None:
        return f"error: no such table {table!r}"
    text = policy.describe(scope, table, create_sql)
    if text is None:
        return f"access denied: {policy.table_denied(scope, table)}"
    return text


def dispatch(
    name: str, args: dict, *, scope: policy.Scope, trace: dict | None = None,
    last_result: dict | None = None,
) -> str:
    """Execute one tool call and return the result as text for the model.

    trace, when given, is filled with the structured outcome for the audit record
    last_result is the trace of this turn's last successful run_sql, the only data make_chart uses
    """
    trace = {} if trace is None else trace
    if name == "list_tables":
        tables = ", ".join(scope.policy.tables)
        if scope.policy.schema_only:
            tables += f"\nschema only, not queryable: {', '.join(scope.policy.schema_only)}"
        return tables

    if name == "describe_table":
        out = _describe_table(args["table"], scope)
        trace["status"] = "access_denied" if out.startswith("access denied") else "ok"
        return out

    if name == "run_sql":
        return _run_sql(args["sql"], scope, trace)

    if name == "make_chart":
        try:
            spec, notes = charts.build(
                args.get("mark"), args.get("x_field"), args.get("y_field"), args.get("title"),
                last_result,
            )
        except charts.ChartError as exc:
            trace.update(status="error", reason=str(exc))
            return f"error: {exc}"
        trace.update(status="ok", chart=spec, points=len(spec["data"]["values"]))
        summary = f"chart ready: {args.get('mark')} of {args.get('y_field')} by {args.get('x_field')}, "
        summary += f"{len(spec['data']['values'])} points"
        return summary + "".join(f"\n{n}" for n in notes)

    if name == "ask_clarifying_question":
        return args["question"]

    if name == "decline":
        return args["reason"]

    return f"error: unknown tool {name!r}"
