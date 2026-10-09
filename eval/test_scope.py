"""Offline checks on the access boundary. No model, no API key.

Each case runs SQL straight through tools.dispatch as a given user, the same path a
model's run_sql call takes, so these are the queries a hostile or confused model could
write.

    python eval/test_scope.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import db, policy, tools  # noqa: E402

DENIED = "access denied"

# user, sql, expected substring of the tool result
CASES = [
    # analyst: own region, active only, T0 + T1
    ("u_ana", "SELECT count(*) AS n FROM customers", "\n6\n"),
    ("u_ana", "SELECT count(*) AS n FROM transactions", "\n10\n"),
    ("u_ana", "SELECT count(*) AS n FROM customers WHERE region = 'EAST'", "\n0\n"),
    ("u_ana", "SELECT national_id FROM customers", DENIED),
    ("u_ana", "SELECT full_name FROM customers WHERE annual_income_usd > 300000", DENIED),
    ("u_ana", "SELECT x FROM (SELECT national_id AS x FROM main.customers)", DENIED),
    ("u_ana", "SELECT count(*) FROM main.customers", DENIED),
    ("u_ana", "WITH c AS (SELECT * FROM main.customers) SELECT count(*) FROM c", DENIED),
    ("u_ana", "SELECT count(*) FROM case_notes", DENIED),
    ("u_ana", "SELECT count(*) FROM users", DENIED),
    ("u_ana", "SELECT sql FROM sqlite_master", DENIED),
    ("u_ana", "SELECT zip_code FROM customers", "use zip3"),
    ("u_ana", "UPDATE users SET role = 'compliance' WHERE user_id = 'u_ana'", DENIED),
    ("u_ana", "SELECT credit_score FROM customers", "error: no such column"),
    # reviewer: adds T2, T3 and case notes for its own region
    ("u_rae", "SELECT avg(annual_income_usd) AS a FROM customers", "211500"),
    ("u_rae", "SELECT count(*) AS n FROM case_notes", "\n3\n"),
    ("u_rae", "SELECT race FROM customers", DENIED),
    # compliance: every region and offboarded, T0 to T4, never T5
    ("u_cora", "SELECT count(*) AS n FROM customers", "\n15\n"),
    ("u_cora", "SELECT national_id FROM customers WHERE customer_id = 'c008'", "NX-4417-DQ"),
    ("u_cora", "SELECT race, count(*) FROM customers GROUP BY race", DENIED),
    # fair_lending: region, segment, T1, T3, T5, no identifiers, no transactions
    ("u_fern", "SELECT sex, count(*) AS n FROM customers GROUP BY sex", "F | 7\nM | 6"),
    ("u_fern", "SELECT customer_id FROM customers", DENIED),
    ("u_fern", "SELECT full_name, race FROM customers", DENIED),
    ("u_fern", "SELECT count(*) FROM transactions", DENIED),
    # admin: users and schema only
    ("u_ops", "SELECT count(*) AS n FROM users", "n\n6"),
    ("u_ops", "SELECT count(*) FROM customers", DENIED),
    ("u_ops", "SELECT * FROM transactions", DENIED),
    ("u_ops", "UPDATE users SET role = 'compliance'", DENIED),
]


def main() -> int:
    failures = 0

    # the model has no way to name a role
    run_sql = next(t for t in tools.TOOLS if t["function"]["name"] == "run_sql")
    if "role" in run_sql["function"]["parameters"]["properties"]:
        print("FAIL  run_sql still takes a role argument")
        failures += 1

    for user_id, sql, want in CASES:
        scope = policy.scope_for(db.get_user(user_id))
        out = tools.dispatch("run_sql", {"sql": sql}, scope=scope)
        ok = want in out
        failures += not ok
        print(f"{'pass' if ok else 'FAIL'}  {user_id:<6} {sql[:70]}")
        if not ok:
            print(f"        want {want!r}, got {out[:200]!r}")

    # a write must never land, whatever it returned
    if db.get_user("u_ana")["role"] != "analyst":
        print("FAIL  u_ana's role changed on disk")
        failures += 1

    print(f"\n{len(CASES) - failures}/{len(CASES)} scope checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
