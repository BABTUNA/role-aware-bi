"""who may see what, resolved on the server

the permission table from the README lives here and only here
identity comes from the users table via db.get_user, never from the model
db.query enforces a Scope on every statement the model writes
"""

import hashlib
import re
from dataclasses import dataclass

# customer columns by tier, as written in the README
T0 = ("customer_id", "full_name", "region", "segment", "risk_score", "onboarded_at", "deleted_at")
T1 = ("zip3", "birth_year", "income_band")
T2 = ("zip_code", "dob")
T3 = ("annual_income_usd",)
T4 = ("national_id", "email", "phone")
T5 = ("race", "ethnicity", "sex")

CUSTOMER_COLUMNS = T0 + T1 + T2 + T3 + T4 + T5

# precise column and the generalized column a role without it gets instead
GENERALIZED = {"zip_code": "zip3", "dob": "birth_year", "annual_income_usd": "income_band"}

# what a role without the precise column must not rebuild from the generalized one
REBUILT_FROM = {
    "dob": "an age or average age from birth_year",
    "annual_income_usd": "an income figure or an income threshold from income_band",
    "zip_code": "a five-digit zip code from zip3",
}

ALL_TABLES = ("customers", "transactions", "alerts", "case_notes", "users")

# disclosure floors from the README
# a customer aggregate needs at least this many distinct customers behind every value
K_MIN = 2
# a protected-class breakdown needs this many customers in the population being broken down
PROTECTED_POPULATION_MIN = 10
# and this many in every reported cell, smaller cells are suppressed
PROTECTED_CELL_MIN = 3


# hidden columns on the server-only check view, never on the view a user's query runs on
# a person key, so the floors count humans and not customer records
PERSON_COLUMN = "__person"
# a record key, for the record counts a user could work out themselves
RECORD_COLUMN = "__record"


class AccessDenied(Exception):
    """the query reached outside the user's scope or below a disclosure floor"""


class Unsupported(Exception):
    """the query shape can't be checked against the disclosure floors, so it is refused"""


@dataclass(frozen=True)
class Policy:
    # tables this role can query
    tables: tuple[str, ...]
    # customer columns this role can read
    customer_columns: tuple[str, ...] = ()
    # rows limited to the user's own region
    own_region_only: bool = False
    # offboarded customers and their activity stay visible
    include_offboarded: bool = False
    # aggregates only, never one row per customer
    aggregate_only: bool = False
    # tables whose schema describe_table shows without allowing queries
    schema_only: tuple[str, ...] = ()


POLICIES = {
    "analyst": Policy(
        tables=("customers", "transactions", "alerts"),
        customer_columns=T0 + T1,
        own_region_only=True,
    ),
    "reviewer": Policy(
        tables=("customers", "transactions", "alerts", "case_notes"),
        customer_columns=T0 + T1 + T2 + T3,
        own_region_only=True,
    ),
    # outranks every role on every column except protected class
    "compliance": Policy(
        tables=("customers", "transactions", "alerts", "case_notes"),
        customer_columns=T0 + T1 + T2 + T3 + T4,
        include_offboarded=True,
    ),
    # region and segment are its only T0 columns, so never customer_id or full_name
    # no transactions either, every transaction row carries a customer_id
    "fair_lending": Policy(
        tables=("customers",),
        customer_columns=("region", "segment") + T1 + T3 + T5,
        aggregate_only=True,
    ),
    # operations account, users and the schema but never a customer or transaction row
    "admin": Policy(
        tables=("users",),
        schema_only=("customers", "transactions", "alerts", "case_notes"),
    ),
}


@dataclass(frozen=True)
class Scope:
    user_id: str
    full_name: str
    role: str
    region: str | None
    policy: Policy


def scope_for(user: dict) -> Scope:
    """turn a row from db.get_user into what that user may see"""
    policy = POLICIES.get(user["role"])
    if policy is None:
        raise PermissionError(f"no access policy for role {user['role']!r}")
    if policy.own_region_only and not user["region"]:
        raise PermissionError(f"{user['user_id']} is region-scoped but has no region")
    return Scope(user["user_id"], user["full_name"], user["role"], user["region"], policy)


def fingerprint(scope: Scope) -> str:
    """changes whenever the user's identity or what they may see changes"""
    raw = f"{scope.user_id}|{scope.role}|{scope.region}|{scope.policy!r}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def views(scope: Scope, person_key: bool = False) -> dict[str, str]:
    """one SELECT per queryable table, installed by db.query as a temp view of the same name

    person_key adds the hidden person and record columns, only for the server's floor checks
    """
    p = scope.policy
    conds = []
    if p.own_region_only:
        conds.append(f"c.region = {_quote(scope.region)}")
    if not p.include_offboarded:
        conds.append("c.deleted_at IS NULL")
    where = " AND ".join(conds) or "1"

    # transactions, alerts and notes inherit the customer row filter through these joins
    in_customers = f"SELECT c.customer_id FROM main.customers c WHERE {where}"
    in_txns = f"SELECT t.txn_id FROM main.transactions t WHERE t.customer_id IN ({in_customers})"
    in_alerts = f"SELECT a.alert_id FROM main.alerts a WHERE a.txn_id IN ({in_txns})"

    columns = ", ".join(f"c.{col} AS {col}" for col in p.customer_columns)
    if person_key:
        columns += f", c.national_id AS {PERSON_COLUMN}, c.customer_id AS {RECORD_COLUMN}"
    bodies = {
        "customers": f"SELECT {columns} FROM main.customers c WHERE {where}",
        "transactions": f"SELECT * FROM main.transactions WHERE customer_id IN ({in_customers})",
        # status is stored as open, OPEN, closed, CLOSED and resolved, the view lowercases it
        "alerts": (
            "SELECT alert_id, txn_id, rule_id, severity, lower(status) AS status "
            f"FROM main.alerts WHERE txn_id IN ({in_txns})"
        ),
        "case_notes": f"SELECT * FROM main.case_notes WHERE alert_id IN ({in_alerts})",
        "users": "SELECT * FROM main.users",
    }
    return {table: bodies[table] for table in p.tables}


def unfiltered_tables(scope: Scope) -> set[str]:
    """queryable tables whose view keeps every row of the underlying table"""
    p = scope.policy
    out = {"users"} & set(p.tables)
    if "customers" in p.tables and not p.own_region_only and p.include_offboarded:
        out.add("customers")
    return out


def row_scope(scope: Scope) -> str | None:
    """plain description of the row filter, None when there are no customer rows at all"""
    p = scope.policy
    if "customers" not in p.tables:
        return None
    where = f"region {scope.region} only" if p.own_region_only else "all regions"
    status = "offboarded customers included" if p.include_offboarded else "active customers only"
    return f"{where}, {status}"


def hidden_columns(scope: Scope) -> list[str]:
    return [c for c in CUSTOMER_COLUMNS if c not in scope.policy.customer_columns]


def _hidden_note(scope: Scope, column: str) -> str:
    instead = GENERALIZED.get(column)
    if instead in scope.policy.customer_columns:
        return f"{column} (use {instead})"
    return column


def describe(scope: Scope, table: str, create_sql: str) -> str | None:
    """the CREATE TABLE text this user may see, None when the table is out of scope"""
    p = scope.policy
    if table in p.schema_only:
        return create_sql + f"\n-- schema only: the {scope.role} role cannot query {table}"
    if table not in p.tables:
        return None
    if table != "customers":
        notes = []
        if row_scope(scope) and table != "users":
            notes.append(f"-- rows: only those belonging to visible customers ({row_scope(scope)})")
        if table == "alerts":
            notes.append("-- status is lowercased in this view: open, closed or resolved")
        return "\n".join([create_sql] + notes)

    hidden = set(hidden_columns(scope))
    kept = []
    for line in create_sql.splitlines():
        stripped = line.strip()
        # section comments name tiers this role may not have, blanks were between them
        if not stripped or stripped.startswith("--"):
            continue
        if stripped.split(" ")[0] in hidden:
            continue
        kept.append(line)
    kept.append(f"-- rows: {row_scope(scope)}")
    if hidden:
        notes = ", ".join(_hidden_note(scope, c) for c in hidden_columns(scope))
        kept.append(f"-- not available to the {scope.role} role: {notes}")
    return "\n".join(kept)


def prompt_access(scope: Scope) -> str:
    """the access section of the system prompt, generated from the same policy db.query enforces"""
    p = scope.policy
    lines = [f"- tables you can query: {', '.join(p.tables)}"]
    if p.schema_only:
        lines.append(
            f"- schema only, no rows: {', '.join(p.schema_only)}. This is an operations "
            "account and never sees a customer, transaction, alert or case note row."
        )
    if row_scope(scope):
        related = [t for t in p.tables if t in ("transactions", "alerts", "case_notes")]
        rows = f"- rows: {row_scope(scope)}"
        if related:
            rows += f". {', '.join(related)} only include rows for those customers"
        lines.append(rows)
    if "customers" in p.tables:
        lines.append(f"- customers columns: {', '.join(p.customer_columns)}")
        hidden = [_hidden_note(scope, c) for c in hidden_columns(scope)]
        if hidden:
            lines.append(f"- not available: {', '.join(hidden)}")
        for column in hidden_columns(scope):
            if column in REBUILT_FROM and GENERALIZED[column] in p.customer_columns:
                lines.append(
                    f"- {column} is restricted, so never compute {REBUILT_FROM[column]}. "
                    f"Decline, say {column} is restricted, and offer {GENERALIZED[column]} instead"
                )
    if p.aggregate_only:
        lines.append("- aggregate results only (count, sum, avg), never one row per customer")
    if "customers" in p.tables:
        lines.append(f"- an aggregate over customers covering fewer than {K_MIN} customers is refused")
    if set(T5) & set(p.customer_columns):
        lines.append(
            f"- a breakdown by race, ethnicity or sex groups by exactly one of them, needs at "
            f"least {PROTECTED_POPULATION_MIN} customers, and cells under {PROTECTED_CELL_MIN} "
            "are suppressed or the whole breakdown is refused"
        )
    return "\n".join(lines)


def table_denied(scope: Scope, table: str) -> str:
    if table in scope.policy.tables:
        return f"query {table} by name, main.{table} is outside the {scope.role} role's scope"
    return f"the {scope.role} role cannot read {table}"


_NO_SUCH_COLUMN = re.compile(r"no such column: (?:\w+\.)?(\w+)")


def hidden_column_reason(scope: Scope, error: str) -> str | None:
    """turn sqlite's 'no such column' for a column the view hides into an access refusal"""
    match = _NO_SUCH_COLUMN.search(error)
    if not match or match.group(1) not in hidden_columns(scope):
        return None
    return f"the {scope.role} role cannot read customers.{_hidden_note(scope, match.group(1))}"
