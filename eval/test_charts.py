"""Offline checks that charts only ever show authorized query results. No model, no API key.

make_chart takes a mark and two column names. The data comes from the last successful
run_sql in the same turn, after scope, floors and suppression. These turns try to get
anything else onto a chart.

    python eval/test_charts.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import audit, baseline  # noqa: E402
from fakes import ScriptedModel  # noqa: E402

BY_RULE = "SELECT a.rule_id, count(*) AS n FROM alerts a GROUP BY a.rule_id"
RACE = "SELECT race, count(*) AS n FROM customers GROUP BY race"
LONG = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 500) SELECT n, n * 2 AS m FROM r"


def chart(x, y, mark="bar", **extra):
    return ("make_chart", {"mark": mark, "x_field": x, "y_field": y, **extra})


def turn(user_id, script, conversation_id=None):
    baseline.openai.OpenAI = lambda: ScriptedModel(script)
    return baseline.run("question", user_id, conversation_id)


def steps(r, tool):
    return [s for s in r.audit["steps"] if s["tool"] == tool]


def check(name, ok, detail=""):
    return (name, ok, detail)


def cases():
    out = []

    r = turn("u_ana", [chart("rule_id", "n")])
    s = steps(r, "make_chart")[0]
    out.append(check("no query in the turn, no chart", s["status"] == "error" and not s["chart"], s))

    r = turn("u_ana", [BY_RULE, chart("rule_id", "n")])
    q, c = steps(r, "run_sql")[0], steps(r, "make_chart")[0]
    expected = [{"x": row[0], "y": row[1]} for row in q["rows"]]
    data = (c.get("chart") or {}).get("data", {}).get("values")
    out.append(check("chart data is exactly the query's two columns", data == expected, data))

    # rows the model passes are ignored, here a national id dressed up as a rule
    r = turn("u_ana", [BY_RULE, chart("rule_id", "n", rows=[{"rule_id": "NX-4417-DQ", "n": 999}])])
    dumped = json.dumps(r.audit)
    out.append(check("rows passed by the model never reach the chart", "NX-4417-DQ" not in dumped and "999" not in dumped))

    # fair_lending race breakdown: two cells are suppressed, they must not become bars
    r = turn("u_fern", [RACE, chart("race", "n")])
    c = steps(r, "make_chart")[0]["chart"] or {}
    xs = [v["x"] for v in c.get("data", {}).get("values", [])]
    ys = [v["y"] for v in c.get("data", {}).get("values", [])]
    subtitle = " ".join(c.get("title", {}).get("subtitle", []))
    out.append(check(
        "suppressed cells stay off the chart",
        xs == ["Asian", "White"] and ys == [4, 6] and "2 suppressed" in subtitle,
        (xs, ys, subtitle),
    ))

    r = turn("u_ana", [LONG, chart("n", "m", mark="line")])
    s = steps(r, "make_chart")[0]
    out.append(check("a truncated result isn't charted", s["status"] == "error" and "truncated" in (s["reason"] or ""), s))

    # a refused query after a good one: the chart uses the good one, never the refused one
    r = turn("u_ana", [BY_RULE, "SELECT national_id, risk_score FROM customers", chart("rule_id", "n")])
    c = steps(r, "make_chart")[0]
    out.append(check("a refused query doesn't replace the last authorized result", c["status"] == "ok" and c["chart"]["encoding"]["x"]["title"] == "rule_id", c))

    r = turn("u_ana", ["SELECT national_id, risk_score FROM customers", chart("national_id", "risk_score")])
    s = steps(r, "make_chart")[0]
    out.append(check("only a refused query in the turn, no chart", s["status"] == "error" and not s["chart"], s))

    # charts bind to this turn's results, not a result from an earlier turn
    baseline.reset_state()
    turn("u_ana", [BY_RULE], conversation_id="conv")
    r = turn("u_ana", [chart("rule_id", "n")], conversation_id="conv")
    s = steps(r, "make_chart")[0]
    out.append(check("a follow-up can't chart the previous turn's result", s["status"] == "error", s))

    r = turn("u_ana", [BY_RULE, chart("national_id", "n")])
    out.append(check("a column that isn't in the result is refused", steps(r, "make_chart")[0]["status"] == "error"))
    r = turn("u_ana", [BY_RULE, chart("rule_id", "rule_id")])
    out.append(check("a non-numeric y is refused", steps(r, "make_chart")[0]["status"] == "error"))
    return out


def main() -> int:
    real_client, real_path = baseline.openai.OpenAI, audit.AUDIT_PATH
    audit.AUDIT_PATH = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
    try:
        baseline.reset_state()
        results = cases()
    finally:
        baseline.openai.OpenAI, audit.AUDIT_PATH = real_client, real_path
        baseline.reset_state()
    for name, ok, detail in results:
        print(f"{'pass' if ok else 'FAIL'}  {name}")
        if not ok and detail:
            print(f"        {str(detail)[:300]}")
    bad = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - bad}/{len(results)} chart checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
