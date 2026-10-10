"""Database access for the baseline agent."""

import os
import pathlib
import sqlite3
import time
from dataclasses import dataclass, field

from . import disclosure, policy
from .policy import AccessDenied, Unsupported  # noqa: F401  re-exported for callers

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fraud.db")

# per statement limits
# wall clock budget, checked by a progress handler every PROGRESS_STEPS vm instructions
QUERY_TIMEOUT_S = 2.0
PROGRESS_STEPS = 10_000
# rows returned to the model, more than this is flagged as truncated
MAX_ROWS = 200
# longest string or blob a statement may build, stops zeroblob(1e9) style memory blowups
MAX_VALUE_BYTES = 1_000_000


class SQLError(Exception):
    """A query failed. The message is returned to the model verbatim."""


@dataclass
class QueryResult:
    rows: list[dict]
    # more than MAX_ROWS rows matched
    truncated: bool = False
    # disclosure rules applied to these rows, for example suppressed cells
    redactions: list[str] = field(default_factory=list)


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


def _authorizer(scope: policy.Scope, denials: list, touched: set, schema_names: set):
    allowed = scope.policy.tables
    unfiltered = policy.unfiltered_tables(scope)

    def check(action, arg1, arg2, dbname, source):
        if action in _READ_ACTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # a read made inside one of the scoped views
            if source in allowed:
                touched.add(source)
                return sqlite3.SQLITE_OK
            # a scoped view read by its name, main.<table> is the raw table
            if arg1 in allowed and dbname != "main":
                touched.add(arg1)
                return sqlite3.SQLITE_OK
            # count(*) on a flattened view reads no column and shows up as the raw table
            # only safe when the view keeps every row anyway
            if arg2 == "" and arg1 in unfiltered:
                touched.add(arg1)
                return sqlite3.SQLITE_OK
            # count(*) over a CTE or table function also reads no column and has no database
            # it reveals a row count of something the query built, never of a real table
            real = arg1 in schema_names or arg1.startswith(("sqlite_", "pragma_"))
            if arg2 == "" and dbname is None and not real:
                return sqlite3.SQLITE_OK
        denials.append((action, arg1, arg2))
        return sqlite3.SQLITE_DENY

    return check


def _open(
    scope: policy.Scope, person_key: bool = False
) -> tuple[sqlite3.Connection, dict[str, list[str]], set[str]]:
    """read-only connection with the scope's temp views, the columns of each view, and every
    name in the real schema

    person_key adds the hidden person and record columns, only for the server's floor checks
    """
    if not os.path.exists(DB_PATH):
        raise RuntimeError(f"{DB_PATH} not found — run `python seed.py` first.")
    conn = sqlite3.connect(pathlib.Path(DB_PATH).as_uri() + "?mode=ro", uri=True)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
    columns = {}
    for name, body in policy.views(scope, person_key).items():
        conn.execute(f"CREATE TEMP VIEW {name} AS {body}")
        columns[name] = [r[1] for r in conn.execute(f"PRAGMA temp.table_info({name})")]
    schema_names = {r[0] for r in conn.execute("SELECT name FROM main.sqlite_master")}
    return conn, columns, schema_names


def _execute(
    conn: sqlite3.Connection, sql: str, scope: policy.Scope, touched: set, schema_names: set,
    cap: bool = True,
) -> tuple[list[str], list[tuple], bool]:
    """one statement under the authorizer and the time limit, returns columns, rows, truncated

    cap=False fetches every row, only for server-side checks that never reach the model
    """
    denials: list = []
    conn.set_authorizer(_authorizer(scope, denials, touched, schema_names))
    deadline = time.monotonic() + QUERY_TIMEOUT_S
    conn.set_progress_handler(lambda: time.monotonic() > deadline, PROGRESS_STEPS)
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS + 1) if cap else cursor.fetchall()
        names = [d[0] for d in cursor.description or []]
    except sqlite3.Error as exc:
        if denials:
            action, table, _ = denials[0]
            if action != sqlite3.SQLITE_READ:
                raise AccessDenied("only read-only SELECT statements are allowed") from exc
            raise AccessDenied(policy.table_denied(scope, table)) from exc
        # writes to a view fail before the authorizer runs
        if "because it is a view" in str(exc):
            raise AccessDenied("only read-only SELECT statements are allowed") from exc
        if "interrupted" in str(exc):
            raise SQLError(
                f"query stopped after {QUERY_TIMEOUT_S:g}s, filter or aggregate it"
            ) from exc
        reason = policy.hidden_column_reason(scope, str(exc))
        if reason:
            raise AccessDenied(reason) from exc
        raise SQLError(str(exc)) from exc
    finally:
        conn.set_progress_handler(None, 0)
        conn.set_authorizer(None)
    if not cap:
        return names, [tuple(r) for r in rows], False
    return names, [tuple(r) for r in rows[:MAX_ROWS]], len(rows) > MAX_ROWS


def query(sql: str, scope: policy.Scope) -> QueryResult:
    """run model-written SQL inside the user's scope

    the connection is read-only
    each table the scope allows is shadowed by a temp view that already filters rows and drops columns
    the authorizer refuses everything else, raw main.<table> reads, other tables, writes, PRAGMA, ATTACH
    disclosure.plan then applies the aggregate floors to anything that read customers
    """
    # a filter that can only match rows outside the scope gets a refusal, not an empty result
    reason = disclosure.out_of_scope_filter(sql, scope)
    if reason:
        raise AccessDenied(reason)

    conn, columns, schema_names = _open(scope)
    try:
        touched: set = set()
        names, rows, truncated = _execute(conn, sql, scope, touched, schema_names)
        redactions: list[str] = []
        plan = disclosure.plan(sql, scope, touched, columns)
        if plan is not None:
            # the floors count people, so the checks run on a second connection whose customers
            # view also carries a person key, the user's own query never runs there
            check_conn, _, _ = _open(scope, person_key=True)
            try:
                _, checked, _ = _execute(check_conn, plan.check_sql, scope, set(), schema_names)
                members = None
                if plan.protected_key or scope.policy.aggregate_only:
                    _, member_rows, _ = _execute(
                        check_conn, plan.members_sql, scope, set(), schema_names, cap=False
                    )
                    members = [r[0] for r in member_rows]
            finally:
                check_conn.close()
            rows, redactions = disclosure.enforce(plan, scope, rows, checked, members)
            disclosure.audit(plan, scope, members)
    finally:
        conn.close()
    return QueryResult([dict(zip(names, r)) for r in rows], truncated, redactions)


def table_sql(table: str) -> str | None:
    """the CREATE TABLE text for one table, matched by exact name"""
    with connect() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone()
    return row["sql"] if row else None
