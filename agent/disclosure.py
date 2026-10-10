"""disclosure floors and out-of-scope filters, checked on the structure of the SQL

the views and authorizer in db.py stay the security boundary
this module only adds rules the views can't express, and it only accepts query shapes it can
check exactly
anything over customers that it can't check is refused as unsupported, never let through
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from .policy import (
    K_MIN, PROTECTED_CELL_MIN, PROTECTED_POPULATION_MIN, T5,
    AccessDenied, Scope, Unsupported,
)

# sqlite's built-in aggregate functions, sqlglot parses some of them as anonymous functions
SQLITE_AGGREGATES = {
    "avg", "count", "group_concat", "max", "min", "sum", "total", "string_agg",
    "json_group_array", "json_group_object", "jsonb_group_array", "jsonb_group_object",
    "median", "percentile", "percentile_cont", "percentile_disc",
}

# the only aggregates an aggregate-only role may use, the rest can return one customer's value
SAFE_AGGREGATES = (exp.Count, exp.Sum, exp.Avg)

# appended to a customer aggregate to count the customers behind each output row
K_COLUMN = "__k"

SIMPLE_SHAPE = (
    "queries that aggregate customers must be one SELECT over customers, optionally joined to "
    "transactions or alerts, with no subqueries, CTEs, UNION or window functions. "
    "rewrite it in that shape or decline"
)


@dataclass
class Plan:
    # the original query with a count of customers appended as the last column
    check_sql: str
    # global aggregate with no GROUP BY, a count of zero customers is not a disclosure
    global_aggregate: bool
    # set for a protected-class breakdown
    population_sql: str | None = None
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
    if isinstance(node, exp.AggFunc):
        return True
    return isinstance(node, exp.Anonymous) and node.name.lower() in SQLITE_AGGREGATES


def _sources(tree) -> dict[str, str]:
    """alias -> table for the FROM and JOIN clauses, refuses anything that isn't a plain table"""
    from_ = tree.args.get("from_")
    if from_ is None:
        raise Unsupported(SIMPLE_SHAPE)
    nodes = [from_.this] + [j.this for j in tree.args.get("joins") or []]
    out = {}
    for node in nodes:
        if not isinstance(node, exp.Table):
            raise Unsupported(SIMPLE_SHAPE)
        out[node.alias_or_name] = node.name
    return out


def _resolve(node, aliases: dict):
    """a select alias used in GROUP BY or HAVING, replaced by the expression it names"""
    if isinstance(node, exp.Column) and not node.table and node.name in aliases:
        return aliases[node.name]
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
    if not isinstance(tree, exp.Select):
        raise Unsupported(SIMPLE_SHAPE)
    nested = [s for s in tree.find_all(exp.Select) if s is not tree]
    if tree.args.get("with_") or nested or tree.find(exp.Window):
        raise Unsupported(SIMPLE_SHAPE)

    sources = _sources(tree)
    customer_aliases = [a for a, t in sources.items() if t == "customers"]
    if len(customer_aliases) != 1:
        raise Unsupported(SIMPLE_SHAPE)
    customer_alias = customer_aliases[0]

    aggregates = [n for n in tree.find_all(exp.Func) if _is_aggregate(n)]
    grouped = tree.args.get("group") is not None
    p = scope.policy

    # one row per customer
    if not aggregates and not grouped:
        if p.aggregate_only:
            raise AccessDenied(
                f"the {scope.role} role only gets aggregates, never one row per customer"
            )
        return None

    if p.aggregate_only:
        unsafe = [n for n in aggregates if not isinstance(n, SAFE_AGGREGATES)]
        if unsafe:
            name = unsafe[0].sql(dialect="sqlite").split("(")[0].lower()
            raise AccessDenied(
                f"the {scope.role} role may aggregate customers with count, sum and avg only, "
                f"{name} can return a single customer's value"
            )

    if len(sources) == 1:
        k_expr = exp.Count(this=exp.Star())
    else:
        # joined to transactions or alerts, it only counts as a customer aggregate when an
        # aggregate reads a customers column
        def from_customers(col: exp.Column) -> bool:
            if col.table:
                return sources.get(col.table) == "customers"
            others = [c for a, t in sources.items() if a != customer_alias for c in columns.get(t, [])]
            return col.name in columns.get("customers", []) and col.name not in others

        if not any(from_customers(c) for n in aggregates for c in n.find_all(exp.Column)):
            return None
        if "customer_id" not in columns.get("customers", []):
            raise Unsupported(SIMPLE_SHAPE)
        k_expr = exp.Count(
            this=exp.Distinct(expressions=[exp.column("customer_id", table=customer_alias)])
        )

    aliases = {e.alias: e.this for e in tree.expressions if isinstance(e, exp.Alias)}
    if K_COLUMN in aliases:
        raise Unsupported(SIMPLE_SHAPE)
    check = tree.select(exp.alias_(k_expr, K_COLUMN))
    result = Plan(check_sql=check.sql(dialect="sqlite"), global_aggregate=not grouped)

    protected = {c.name.lower() for c in tree.find_all(exp.Column) if c.name.lower() in T5}
    if protected:
        result.population_sql, result.key_positions = _protected_plan(tree, aliases, protected)
    return result


def _protected_plan(tree, aliases: dict, protected: set[str]) -> tuple[str, tuple[int, ...]]:
    """only one shape is reported: GROUP BY exactly one protected column, no other use of any"""
    group = tree.args.get("group")
    keys = [_resolve(g, aliases) for g in (group.expressions if group else [])]
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

    population = tree.copy()
    population.set("expressions", [exp.alias_(exp.Count(this=exp.Star()), "n")])
    for k in ("group", "having", "order", "limit", "offset", "distinct"):
        population.set(k, None)
    return population.sql(dialect="sqlite"), tuple(positions)


SUPPRESSED = f"suppressed (<{PROTECTED_CELL_MIN})"


def enforce(
    plan: Plan, scope: Scope, rows: list[tuple], checked: list[tuple], population: int | None
) -> tuple[list[tuple], list[str]]:
    """apply the floors to the original rows using the counts from the check query"""
    # the check query is the original plus one column, anything else means it was rewritten wrong
    if len(checked) != len(rows) or [tuple(r[:-1]) for r in checked] != [tuple(r) for r in rows]:
        raise Unsupported(SIMPLE_SHAPE)
    counts = [r[-1] for r in checked]

    if plan.population_sql is None:
        small = [k for k in counts if k < K_MIN]
        if plan.global_aggregate and counts == [0]:
            return rows, []
        if small:
            raise AccessDenied(
                f"this aggregate covers fewer than {K_MIN} customers"
                + (" in at least one group" if not plan.global_aggregate else "")
                + ", below the disclosure floor"
            )
        return rows, []

    if population < PROTECTED_POPULATION_MIN:
        raise AccessDenied(
            f"a protected-class breakdown needs at least {PROTECTED_POPULATION_MIN} customers "
            "in the population, this one has fewer"
        )
    suppressed = [i for i, k in enumerate(counts) if k < PROTECTED_CELL_MIN]
    hidden = sum(counts[i] for i in suppressed)
    # one hidden cell is the known total minus the others
    # several hidden cells are pinned when they must all be 1 or all be 2
    m = len(suppressed)
    if m == 1 or (m > 1 and hidden in (m, 2 * m)):
        raise AccessDenied(
            f"this protected-class breakdown has cells under {PROTECTED_CELL_MIN} customers that "
            "could be worked out from the total even if suppressed, so it can't be reported"
        )
    if not suppressed:
        return rows, []
    out = []
    for i, row in enumerate(rows):
        if i in suppressed:
            row = tuple(v if j in plan.key_positions else SUPPRESSED for j, v in enumerate(row))
        out.append(row)
    return out, [f"{m} of {len(rows)} cells had fewer than {PROTECTED_CELL_MIN} customers and were suppressed"]
