"""Database access for the baseline agent."""

import os
import pathlib
import sqlite3

from . import policy

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fraud.db")


class SQLError(Exception):
    """A query failed. The message is returned to the model verbatim."""


class AccessDenied(Exception):
    """the query reached outside the user's scope, returned to the model as a refusal"""


def connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise RuntimeError(f"{DB_PATH} not found — run `python seed.py` first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_user(user_id: str) -> dict:
    """The authenticated identity. This is the only trustworthy source of role and region."""
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id, full_name, role, region FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"no such user: {user_id}")
    return dict(row)


# statement kinds a plain read needs, everything else is refused
_READ_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _authorizer(scope: policy.Scope, denials: list):
    allowed = scope.policy.tables
    unfiltered = policy.unfiltered_tables(scope)

    def check(action, arg1, arg2, dbname, source):
        if action in _READ_ACTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # a read made inside one of the scoped views
            if source in allowed:
                return sqlite3.SQLITE_OK
            # a scoped view read by its name, main.<table> is the raw table
            if arg1 in allowed and dbname != "main":
                return sqlite3.SQLITE_OK
            # count(*) on a flattened view reads no column and shows up as the raw table
            # only safe when the view keeps every row anyway
            if arg2 == "" and arg1 in unfiltered:
                return sqlite3.SQLITE_OK
        denials.append((action, arg1, arg2))
        return sqlite3.SQLITE_DENY

    return check


def query(sql: str, scope: policy.Scope) -> list[dict]:
    """run model-written SQL inside the user's scope

    the connection is read-only
    each table the scope allows is shadowed by a temp view that already filters rows and drops columns
    the authorizer refuses everything else, raw main.<table> reads, other tables, writes, PRAGMA, ATTACH
    """
    if not os.path.exists(DB_PATH):
        raise RuntimeError(f"{DB_PATH} not found — run `python seed.py` first.")
    conn = sqlite3.connect(pathlib.Path(DB_PATH).as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    denials: list = []
    try:
        for name, body in policy.views(scope).items():
            conn.execute(f"CREATE TEMP VIEW {name} AS {body}")
        conn.set_authorizer(_authorizer(scope, denials))
        try:
            rows = conn.execute(sql).fetchall()
        except sqlite3.Error as exc:
            if denials:
                action, table, _ = denials[0]
                if action != sqlite3.SQLITE_READ:
                    raise AccessDenied("only read-only SELECT statements are allowed") from exc
                raise AccessDenied(policy.table_denied(scope, table)) from exc
            # writes to a view fail before the authorizer runs
            if "because it is a view" in str(exc):
                raise AccessDenied("only read-only SELECT statements are allowed") from exc
            reason = policy.hidden_column_reason(scope, str(exc))
            if reason:
                raise AccessDenied(reason) from exc
            raise SQLError(str(exc)) from exc
    finally:
        conn.close()
    return [dict(r) for r in rows]


def table_sql(table: str) -> str | None:
    """the CREATE TABLE text for one table, matched by exact name"""
    with connect() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone()
    return row["sql"] if row else None
