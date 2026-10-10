"""Offline checks on the audit record. No model, no API key.

Turns are driven by the fake model client from test_scope.py, writing to a temporary audit
file. The record must answer "what did the agent see, on whose authority" without holding
anything the user wasn't shown, and the sanitized view must hold nothing internal.

    python eval/test_audit.py
"""

import json
import logging
import os
import stat
import sys
import tempfile
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import audit, baseline, db  # noqa: E402
from test_scope import FakeModel  # noqa: E402

RACE_ALL = "SELECT race, count(*) AS n FROM customers GROUP BY race"
CARVE_OUT = "SELECT race, count(*) AS n FROM customers WHERE zip3 <> '940' GROUP BY race"

# keys that must never reach the frontend
INTERNAL_KEYS = {"views", "policy_fingerprint", "floor_checks", "model_saw", "duration_ms"}


def drive(user_id: str, script: list, conversation_id: str | None = None, client=None):
    baseline.openai.OpenAI = client or (lambda: FakeModel([], list(script)))
    return baseline.run("question", user_id, conversation_id)


def records(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def restricted_values(user_id: str) -> list[str]:
    """values the acting user may not see, which must not appear anywhere in their records"""
    user = db.get_user(user_id)
    with db.connect() as conn:
        customers = [dict(r) for r in conn.execute("SELECT * FROM customers")]
    in_region = {c["full_name"] for c in customers if c["region"] == user["region"]}
    values = []
    for c in customers:
        # direct identifiers and precise quasi-identifiers, none of these users has them
        values += [c["national_id"], c["email"], c["phone"], c["dob"]]
        if user["region"] and c["region"] != user["region"]:
            values.append(c["customer_id"])
            if c["full_name"] not in in_region:
                values.append(c["full_name"])
    return values


def keys_in(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys_in(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in keys_in(v)}
    return set()


def check_record_shape(path: str) -> list[str]:
    failures = []
    before = len(records(path))
    r = drive("u_fern", [RACE_ALL, CARVE_OUT])
    rows = records(path)
    if len(rows) != before + 1:
        return [f"one turn wrote {len(rows) - before} records"]
    rec = rows[-1]

    if rec["identity"] != {"user_id": "u_fern", "full_name": "Fern Aguilar", "role": "fair_lending", "region": None}:
        failures.append(f"identity is {rec['identity']}")
    auth = rec["authority"]
    if auth["rows"] != "all regions, active customers only" or "customer_id" not in auth["withheld_columns"]:
        failures.append(f"resolved scope is {auth}")
    if "deleted_at IS NULL" not in auth["views"].get("customers", ""):
        failures.append("the view SQL that applies the scope is missing")

    first, second = rec["steps"][0], rec["steps"][1]
    check = (first.get("floor_checks") or [{}])[0]
    if first["status"] != "ok" or first["row_count"] != 4 or not first["redactions"]:
        failures.append(f"first query step is {first}")
    if check.get("check") != "protected_class" or check.get("decision") != "suppressed" or check.get("population") != 12:
        failures.append(f"floor check summary is {check}")
    if second["status"] != "access_denied" or "population differs" not in (second["reason"] or ""):
        failures.append(f"refused query step is {second}")
    seen = [line.split("] ", 1)[1] for line in r.transcript if line.startswith("[tool_result run_sql]")]
    if [s["model_saw"] for s in rec["steps"]] != seen:
        failures.append("model_saw differs from what the model was actually shown")
    if rec["outcome"]["status"] != "declined" or not rec["outcome"]["refusal"]:
        failures.append(f"outcome is {rec['outcome']}")
    return failures


def check_no_restricted_data(path: str) -> list[str]:
    failures = []
    scripts = {
        # fair_lending floor checks read national_id on the server, none of it may be stored
        "u_fern": [RACE_ALL, CARVE_OUT, "SELECT birth_year, avg(annual_income_usd) FROM customers GROUP BY birth_year HAVING count(*) >= 2"],
        # an analyst's refused and allowed queries, plus an attempt at another region
        "u_ana": ["SELECT full_name, risk_score FROM customers", "SELECT national_id FROM customers",
                  "SELECT count(*) FROM customers WHERE region = 'EAST'", "SELECT * FROM main.customers"],
    }
    # random ids can contain a customer id by chance, c009 turned up inside a turn id once
    ids = ("turn_id", "conversation_id")
    for user_id, script in scripts.items():
        r = drive(user_id, script)
        text = json.dumps({k: v for k, v in records(path)[-1].items() if k not in ids})
        shown = json.dumps({k: v for k, v in r.audit.items() if k not in ids})
        leaked = [v for v in restricted_values(user_id) if v in text]
        if leaked:
            failures.append(f"{user_id}'s server-side record holds {leaked[:4]}")
        leaked = [v for v in restricted_values(user_id) if v in shown]
        if leaked:
            failures.append(f"{user_id}'s sanitized record holds {leaked[:4]}")
    return failures


def check_sanitized(path: str) -> list[str]:
    failures = []
    r = drive("u_fern", [RACE_ALL])
    view = r.audit
    if view is None:
        return ["AgentResult.audit is empty"]
    internal = INTERNAL_KEYS & keys_in(view)
    if internal:
        failures.append(f"sanitized record exposes {sorted(internal)}")
    # national_id may only appear as a column name in the user's own withheld list
    outside_scope = json.dumps({k: v for k, v in view.items() if k != "scope"})
    if "__person" in json.dumps(view) or "national_id" in outside_scope:
        failures.append("sanitized record mentions the hidden person key")
    step = view["steps"][0]
    if step.get("sql") != RACE_ALL or step.get("columns") != ["race", "n"]:
        failures.append(f"sanitized step is {step}")
    if not any("suppressed" in str(v) for row in step.get("rows", []) for v in row):
        failures.append("suppressed cells lost their marker in the sanitized rows")
    if view["scope"].get("rows") != "all regions, active customers only":
        failures.append(f"sanitized scope is {view['scope']}")
    if view["turn_id"] != records(path)[-1]["turn_id"]:
        failures.append("sanitized record doesn't point at the server-side record")
    return failures


def check_fail_closed() -> list[str]:
    real = audit.AUDIT_PATH
    # the failed write is logged as an error on purpose, keep it out of the test output
    logger = logging.getLogger("agent.baseline")
    with tempfile.TemporaryDirectory() as d:
        # a directory can't be opened for append
        audit.AUDIT_PATH = d
        logger.disabled = True
        try:
            r = drive("u_ana", ["SELECT count(*) AS n FROM customers"])
        finally:
            audit.AUDIT_PATH = real
            logger.disabled = False
    if r.answer or not r.error or r.audit is not None:
        return [f"an unrecorded turn still answered: answer={r.answer!r} error={r.error!r}"]
    return []


def check_permissions(path: str) -> list[str]:
    mode = stat.S_IMODE(os.stat(path).st_mode)
    return [] if mode == 0o600 else [f"audit file mode is {oct(mode)}"]


class Broken:
    """a model client whose first call returns arguments that aren't JSON, then fails outright"""

    def __init__(self):
        self.calls = 0
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("model client fell over")
        call = NS(id="c1", function=NS(name="run_sql", arguments="{not json"))
        message = NS(content=None, tool_calls=[call], refusal=None)
        return NS(choices=[NS(message=message)], usage=NS(prompt_tokens=0, completion_tokens=0))


def check_every_exit_is_recorded(path: str) -> list[str]:
    before = len(records(path))
    try:
        drive("u_ana", [], client=lambda: Broken())
    except RuntimeError:
        pass
    rows = records(path)
    if len(rows) != before + 1:
        return ["a turn that raised left no record"]
    rec = rows[-1]
    if rec["outcome"]["status"] != "error" or rec["steps"][0]["status"] != "bad_arguments":
        return [f"crashed turn recorded as {rec['outcome']} with steps {rec['steps']}"]
    return []


def main() -> int:
    real_client, real_path = baseline.openai.OpenAI, audit.AUDIT_PATH
    failures: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.jsonl")
        audit.AUDIT_PATH = path
        try:
            for name, check in [
                ("record has identity, scope, SQL, what the model saw, redactions, outcome", lambda: check_record_shape(path)),
                ("no restricted value in either record", lambda: check_no_restricted_data(path)),
                ("sanitized record holds nothing internal", lambda: check_sanitized(path)),
                ("no record, no answer", check_fail_closed),
                ("audit file is readable by its owner only", lambda: check_permissions(path)),
                ("a turn that crashes still leaves a record", lambda: check_every_exit_is_recorded(path)),
            ]:
                baseline.reset_state()
                failures[name] = check()
        finally:
            baseline.openai.OpenAI, audit.AUDIT_PATH = real_client, real_path
            baseline.reset_state()

    for name, problems in failures.items():
        print(f"{'pass' if not problems else 'FAIL'}  {name}")
        for p in problems:
            print(f"        {p}")
    bad = sum(1 for p in failures.values() if p)
    print(f"\n{len(failures) - bad}/{len(failures)} audit checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
