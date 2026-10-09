"""Tool definitions and dispatch for the baseline agent.

This is the layer between the model and the data. Read it closely.
"""

import logging

from . import db, policy

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
                "Render a chart. Returns a Vega-Lite spec — do not attempt to draw the "
                "chart yourself. Pass the rows you want plotted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mark": {"type": "string", "enum": ["bar", "line", "point"]},
                    "x_field": {"type": "string"},
                    "y_field": {"type": "string"},
                    "title": {"type": "string"},
                    "rows": {
                        "type": "array",
                        "description": "The data to plot, as a list of objects.",
                        "items": {"type": "object"},
                    },
                },
                "required": ["mark", "x_field", "y_field", "rows"],
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
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]

TERMINAL_TOOLS = {"ask_clarifying_question", "decline"}


def _run_sql(sql: str, scope: policy.Scope) -> str:
    try:
        rows = db.query(sql, scope)
    except db.AccessDenied as exc:
        log.info("user=%s denied sql=%s reason=%s", scope.user_id, sql, exc)
        return f"access denied: {exc}"
    except db.SQLError as exc:
        return f"error: {exc}"
    log.info("user=%s sql=%s rows=%d", scope.user_id, sql, len(rows))

    # tells the model a zero or a short list may be the scope, not the data
    note = f"\nscope: {policy.row_scope(scope)}" if policy.row_scope(scope) else ""
    if not rows:
        return "0 rows" + note
    header = " | ".join(rows[0].keys())
    body = "\n".join(" | ".join(str(v) for v in r.values()) for r in rows)
    return f"{len(rows)} row(s)\n{header}\n{body}{note}"


def _describe_table(table: str, scope: policy.Scope) -> str:
    create_sql = db.table_sql(table)
    if create_sql is None:
        return f"error: no such table {table!r}"
    text = policy.describe(scope, table, create_sql)
    if text is None:
        return f"access denied: {policy.table_denied(scope, table)}"
    return text


def dispatch(name: str, args: dict, *, scope: policy.Scope) -> str:
    """Execute one tool call and return the result as text for the model."""
    if name == "list_tables":
        tables = ", ".join(scope.policy.tables)
        if scope.policy.schema_only:
            tables += f"\nschema only, not queryable: {', '.join(scope.policy.schema_only)}"
        return tables

    if name == "describe_table":
        return _describe_table(args["table"], scope)

    if name == "run_sql":
        return _run_sql(args["sql"], scope)

    if name == "make_chart":
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": args.get("title", ""),
            "mark": args["mark"],
            "data": {"values": args["rows"]},
            "encoding": {
                "x": {"field": args["x_field"], "type": "nominal"},
                "y": {"field": args["y_field"], "type": "quantitative"},
            },
        }
        return f"chart rendered: {spec}"

    if name == "ask_clarifying_question":
        return args["question"]

    if name == "decline":
        return args["reason"]

    return f"error: unknown tool {name!r}"
