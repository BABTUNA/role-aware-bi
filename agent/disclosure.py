"""disclosure floors and out-of-scope filters, checked on the structure of the SQL

the views and authorizer in db.py stay the security boundary
this module only adds rules the views can't express, and it only accepts query shapes it can
check exactly
anything over customers that it can't check is refused as unsupported, never let through
"""

import threading
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from .policy import (
    K_MIN, PERSON_COLUMN, PROTECTED_CELL_MIN, PROTECTED_POPULATION_MIN, RECORD_COLUMN, T5,
    AccessDenied, Scope, Unsupported,
)

# sqlite's built-in aggregate functions, sqlglot parses some of them as anonymous functions
SQLITE_AGGREGATES = {
    "avg", "count", "group_concat", "max", "min", "sum", "total", "string_agg",
    "json_group_array", "json_group_object", "jsonb_group_array", "jsonb_group_object",
    "median", "percentile", "percentile_cont", "percentile_disc",
}

# window-only functions that rank or pick rows, they never combine values across customers
# sqlglot types some of them as aggregates
WINDOW_ONLY = tuple(
    getattr(exp, name) for name in (
        "Rank", "DenseRank", "RowNumber", "PercentRank", "CumeDist", "Ntile",
        "Lag", "Lead", "FirstValue", "LastValue", "NthValue",
    ) if hasattr(exp, name)
)

# the only aggregates an aggregate-only role may use, the rest can return one customer's value
SAFE_AGGREGATES = (exp.Count, exp.Sum, exp.Avg)

# appended to a customer aggregate, people and customer records behind each output row
K_COLUMN = "__k"
N_COLUMN = "__n"

SIMPLE_SHAPE = (
    "queries that aggregate customers must be one SELECT over customers, optionally joined to "
    "transactions or alerts, with no CTEs, UNION, window functions, subqueries in FROM, or "
    "subqueries that aggregate. rewrite it in that shape or decline"
)
NO_SUBQUERIES = (
    "aggregates for this role must be one SELECT over customers with no subqueries, CTEs, "
    "UNION or window functions. rewrite it in that shape or decline"
)


@dataclass
class Plan:
    # the original query with people and record counts appended as the last two columns
    check_sql: str
    # the distinct people the query's WHERE selects, before any grouping
    members_sql: str
    # global aggregate with no GROUP BY, a count of zero customers is not a disclosure
    global_aggregate: bool
    # the protected column a breakdown groups by, None for any other aggregate
    protected_key: str | None = None
    # positions of the protected-class group key in the select list
    key_positions: tuple[int, ...] = ()


def _parse(sql: str):
    try:
        trees = sqlglot.parse(sql, read="sqlite")
    except sqlglot.errors.SqlglotError:
        return None
    if len(trees) != 1 or trees[0] is None:
        return None
    return trees[0]


def _literals(node) -> list[str]:
    return [n.this for n in node if isinstance(n, exp.Literal) and n.is_string]


def out_of_scope_filter(sql: str, scope: Scope) -> str | None:
    """a filter that can only ever match rows outside the scope, so the honest answer is a refusal not 0

    a WEST analyst asking about EAST would otherwise get an empty result that reads as 'none'
    """
    p = scope.policy
    if "customers" not in p.tables:
        return None
    tree = _parse(sql)
    if tree is None:
        return None

    if p.own_region_only:
        for node in tree.find_all(exp.EQ, exp.In):
            if isinstance(node, exp.EQ):
                column, values = node.this, _literals([node.expression])
                if not isinstance(column, exp.Column):
                    column, values = node.expression, _literals([node.this])
            else:
                column, values = node.this, _literals(node.expressions)
            if not isinstance(column, exp.Column) or column.name.lower() != "region":
                continue
            outside = [v for v in values if v.upper() != scope.region.upper()]
            if outside:
                return (
                    f"the {scope.role} role can only see region {scope.region}, "
                    f"{', '.join(outside)} is outside its scope"
                )

    if not p.include_offboarded:
        for node in tree.find_all(exp.Not):
            inner = node.this
            if (
                isinstance(inner, exp.Is)
                and isinstance(inner.this, exp.Column)
                and inner.this.name.lower() == "deleted_at"
                and isinstance(inner.expression, exp.Null)
            ):
                return (
                    f"the {scope.role} role only sees active customers, "
                    "offboarded customers are outside its scope"
                )
    return None


def _is_aggregate(node) -> bool:
    """combines values across rows, a plain aggregate or an aggregate used as a window"""
    if isinstance(node, WINDOW_ONLY):
        return False
    if isinstance(node, exp.AggFunc):
        return True
    return isinstance(node, exp.Anonymous) and node.name.lower() in SQLITE_AGGREGATES


def _aggregates(node) -> list:
    return [n for n in node.find_all(exp.Func) if _is_aggregate(n)]


def _own_aggregates(select) -> list:
    """aggregates at this SELECT's own level, not inside its subqueries"""
    nested = lambda n: isinstance(n, exp.Select) and n is not select  # noqa: E731
    return [n for n in select.walk(prune=nested) if isinstance(n, exp.Func) and _is_aggregate(n)]


def _reads_customers(node) -> bool:
    return any(t.name == "customers" for t in node.find_all(exp.Table))


def _sources(tree, message: str) -> dict[str, str]:
    """alias -> table for the FROM and JOIN clauses, refuses anything that isn't a plain table"""
    from_ = tree.args.get("from_")
    if from_ is None:
        raise Unsupported(message)
    nodes = [from_.this] + [j.this for j in tree.args.get("joins") or []]
    out = {}
    for node in nodes:
        if not isinstance(node, exp.Table):
            raise Unsupported(message)
        out[node.alias_or_name] = node.name
    return out


def _resolve(node, aliases: dict, select: list):
    """a select alias or ordinal used in GROUP BY, replaced by the expression it names"""
    if isinstance(node, exp.Column) and not node.table and node.name in aliases:
        return aliases[node.name]
    if isinstance(node, exp.Literal) and not node.is_string and str(node.this).isdigit():
        i = int(node.this) - 1
        if 0 <= i < len(select):
            e = select[i]
            return e.this if isinstance(e, exp.Alias) else e
    return node


def plan(sql: str, scope: Scope, touched: set[str], columns: dict[str, list[str]]) -> Plan | None:
    """decide whether a query that already passed the authorizer needs a disclosure check

    returns None when no floor applies
    raises AccessDenied or Unsupported to refuse outright
    """
    # transaction and alert totals are business metrics, the floors don't apply
    if "customers" not in touched:
        return None

    tree = _parse(sql)
    if tree is None:
        raise Unsupported(SIMPLE_SHAPE)
    p = scope.policy
    grouped = isinstance(tree, exp.Select) and tree.args.get("group") is not None

    # nothing combines values across customers, so there is no aggregate to hold to a floor
    # a role that may read rows gets them whatever the shape, subqueries and ranking included
    if not _aggregates(tree):
        if not p.aggregate_only:
            return None
        if not grouped:
            raise AccessDenied(
                f"the {scope.role} role only gets aggregates, never one row per customer"
            )

    message = NO_SUBQUERIES if p.aggregate_only else SIMPLE_SHAPE
    if not isinstance(tree, exp.Select) or tree.args.get("with_") or tree.find(exp.Window):
        raise Unsupported(message)
    for sub in tree.find_all(exp.Select):
        if sub is tree:
            continue
        # for an aggregate-only role even a plain filter subquery is a yes/no question about
        # rows it may not see, the outer count comes back whole or zero
        if p.aggregate_only:
            raise Unsupported(NO_SUBQUERIES)
        # a subquery that aggregates customers can leak its count through the outer result
        # one that only aggregates transactions or alerts is a business metric used as a filter
        if (_aggregates(sub) or sub.args.get("group")) and _reads_customers(sub):
            raise Unsupported(SIMPLE_SHAPE)

    aggregates = _own_aggregates(tree)
    # the only aggregates sit in business-metric filter subqueries, the query returns rows
    if not aggregates and not grouped:
        return None
    sources = _sources(tree, message)
    customer_aliases = [a for a, t in sources.items() if t == "customers"]
    if len(customer_aliases) > 1:
        raise Unsupported(message)
    if not customer_aliases:
        # customers only appears in a filter subquery, the outer total is over transactions or
        # alerts, which is a business metric
        if p.aggregate_only:
            raise Unsupported(message)
        return None
    customer_alias = customer_aliases[0]

    if p.aggregate_only:
        unsafe = [n for n in aggregates if not isinstance(n, SAFE_AGGREGATES)]
        if unsafe:
            name = unsafe[0].sql(dialect="sqlite").split("(")[0].lower()
            raise AccessDenied(
                f"the {scope.role} role may aggregate customers with count, sum and avg only, "
                f"{name} can return a single customer's value"
            )

    if len(sources) > 1:
        # joined to transactions or alerts, it only counts as a customer aggregate when an
        # aggregate reads a customers column
        def from_customers(col: exp.Column) -> bool:
            if col.table:
                return sources.get(col.table) == "customers"
            others = [c for a, t in sources.items() if a != customer_alias for c in columns.get(t, [])]
            return col.name in columns.get("customers", []) and col.name not in others

        if not any(from_customers(c) for n in aggregates for c in n.find_all(exp.Column)):
            return None

    aliases = {e.alias: e.this for e in tree.expressions if isinstance(e, exp.Alias)}
    if aliases.keys() & {K_COLUMN, N_COLUMN, PERSON_COLUMN, RECORD_COLUMN}:
        raise Unsupported(message)
    person = exp.column(PERSON_COLUMN, table=customer_alias)
    # people, so two records for one human count once
    people = exp.Count(this=exp.Distinct(expressions=[person.copy()]))
    records = exp.Count(this=exp.Distinct(expressions=[exp.column(RECORD_COLUMN, table=customer_alias)]))
    check = tree.select(exp.alias_(people, K_COLUMN), exp.alias_(records, N_COLUMN))

    members = tree.copy()
    members.set("expressions", [person.copy()])
    for k in ("group", "having", "order", "limit", "offset"):
        members.set(k, None)
    members.set("distinct", exp.Distinct())

    result = Plan(
        check_sql=check.sql(dialect="sqlite"),
        members_sql=members.sql(dialect="sqlite"),
        global_aggregate=not grouped,
    )
    protected = {c.name.lower() for c in tree.find_all(exp.Column) if c.name.lower() in T5}
    if protected:
        result.protected_key, result.key_positions = _protected_plan(tree, aliases, protected)
    return result


def _protected_plan(tree, aliases: dict, protected: set[str]) -> tuple[str, tuple[int, ...]]:
    """only one shape is reported: GROUP BY exactly one protected column, no other use of any"""
    group = tree.args.get("group")
    keys = [_resolve(g, aliases, tree.expressions) for g in (group.expressions if group else [])]
    if len(keys) != 1 or not isinstance(keys[0], exp.Column) or keys[0].name.lower() not in T5:
        raise Unsupported(
            "a protected-class breakdown must GROUP BY exactly one of race, ethnicity or sex"
        )
    key = keys[0].name.lower()
    where = tree.args.get("where")
    if protected != {key} or (where and any(c.name.lower() in T5 for c in where.find_all(exp.Column))):
        raise Unsupported(
            "protected-class columns can only appear as the single GROUP BY key, "
            "not in filters or other expressions"
        )
    if any(tree.args.get(k) for k in ("having", "limit", "offset", "distinct")):
        raise Unsupported(
            "a protected-class breakdown can't use HAVING, LIMIT or DISTINCT, every cell has to be checked"
        )
    positions = []
    for i, e in enumerate(tree.expressions):
        if isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star)):
            raise Unsupported("list the columns of a protected-class breakdown instead of *")
        inner = e.this if isinstance(e, exp.Alias) else e
        if isinstance(inner, exp.Column) and inner.name.lower() == key:
            positions.append(i)
    return key, tuple(positions)


SUPPRESSED = f"suppressed (<{PROTECTED_CELL_MIN})"


def enforce(
    plan: Plan, scope: Scope, rows: list[tuple], checked: list[tuple], members: list | None
) -> tuple[list[tuple], list[str]]:
    """apply the floors to the original rows using the counts from the check query"""
    # the check query is the original plus two columns, anything else means it was rewritten wrong
    if len(checked) != len(rows) or [tuple(r[:-2]) for r in checked] != [tuple(r) for r in rows]:
        raise Unsupported(SIMPLE_SHAPE)
    people = [r[-2] for r in checked]
    records = [r[-1] for r in checked]

    if plan.protected_key is None:
        if plan.global_aggregate and people == [0]:
            return rows, []
        if any(k < K_MIN for k in people):
            raise AccessDenied(
                f"this aggregate covers fewer than {K_MIN} people"
                + (" in at least one group" if not plan.global_aggregate else "")
                + ", below the disclosure floor"
            )
        return rows, []

    if len(members) < PROTECTED_POPULATION_MIN:
        raise AccessDenied(
            f"a protected-class breakdown needs at least {PROTECTED_POPULATION_MIN} people "
            "in the population, this one has fewer"
        )
    suppressed = [i for i, k in enumerate(people) if k < PROTECTED_CELL_MIN]
    m = len(suppressed)
    # one hidden cell is the known total minus the others
    # several hidden cells are pinned when they must all be 1 or all be 2, checked on people
    # and on the record counts a user can work out from count(*)
    pinned = any(
        sum(counts[i] for i in suppressed) in (m, 2 * m) for counts in (people, records)
    )
    if m == 1 or (m > 1 and pinned):
        raise AccessDenied(
            f"this protected-class breakdown has cells under {PROTECTED_CELL_MIN} people that "
            "could be worked out from the total even if suppressed, so it can't be reported"
        )
    if not suppressed:
        return rows, []
    out = []
    for i, row in enumerate(rows):
        if i in suppressed:
            row = tuple(v if j in plan.key_positions else SUPPRESSED for j, v in enumerate(row))
        out.append(row)
    return out, [f"{m} of {len(rows)} cells had fewer than {PROTECTED_CELL_MIN} people and were suppressed"]


# per user, the populations of aggregate-only answers already given, as (kind, people)
_ANSWERED: dict[str, list[tuple[str, frozenset]]] = {}
_ANSWERED_LOCK = threading.Lock()


def audit(plan: Plan, scope: Scope, members: list | None) -> None:
    """refuse an aggregate-only answer whose population nearly matches one already given

    two answers over populations that differ by a few people describe those few people
    the difference has to clear the same floor as a single answer would
    recorded per user, not per conversation, so a new chat doesn't reset it
    """
    if not scope.policy.aggregate_only or members is None:
        return
    kind = f"protected:{plan.protected_key}" if plan.protected_key else "aggregate"
    floor = PROTECTED_POPULATION_MIN if plan.protected_key else K_MIN
    population = frozenset(members)
    with _ANSWERED_LOCK:
        answered = _ANSWERED.setdefault(scope.user_id, [])
        for seen_kind, seen in answered:
            if seen_kind == kind and 0 < len(population ^ seen) < floor:
                raise AccessDenied(
                    f"this population differs from one already reported to you by fewer than "
                    f"{floor} people, so the two answers together would describe them individually"
                )
        if (kind, population) not in answered:
            answered.append((kind, population))


def reset_audit() -> None:
    with _ANSWERED_LOCK:
        _ANSWERED.clear()
