"""Offline checks on the HTTP API: sessions, identity switching and stale answers. No API key.

The agent runs against a scripted fake model. A browser has one cookie jar, so switching
identity replaces the session cookie; a request already in flight still carries the old one.

    python eval/test_server.py
"""

import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from agent import audit, baseline, db  # noqa: E402
from app import server  # noqa: E402
from fakes import ScriptedModel  # noqa: E402

INTERNAL = ("views", "model_saw", "floor_checks", "policy_fingerprint", "__person")


def use_model(script=(), sent=None, gate=None, entered=None):
    baseline.openai.OpenAI = lambda: ScriptedModel(script, sent, gate, entered)


def login(client, user_id):
    r = client.post("/api/session", json={"user_id": user_id})
    assert r.status_code == 200, r.text
    return r.json()


def ask(client, conversation_id, question="question", **extra):
    return client.post("/api/chat", json={"conversation_id": conversation_id, "question": question, **extra})


def in_flight(cookie, conversation_id, out):
    """send a chat from a separate client holding the old cookie, like a request already sent"""
    c = TestClient(server.app)
    c.cookies.set(server.COOKIE, cookie)
    out.append(ask(c, conversation_id))


def cases():
    out = []
    c = TestClient(server.app)

    out.append(("chat without a session is refused", ask(c, "c_x").status_code == 401))
    r = c.post("/api/session", json={"user_id": "u_nobody"})
    out.append(("an unknown identity is refused", r.status_code == 404))

    sent: list = []
    use_model(sent=sent)
    cora = login(c, "u_cora")
    r = ask(c, cora["conversation_id"], "cora's private question")
    out.append(("a chat answers for the session's identity",
                r.status_code == 200 and r.json()["audit"]["identity"]["user_id"] == "u_cora"))
    old_cookie = c.cookies.get(server.COOKIE)

    ana = login(c, "u_ana")
    out.append(("switching issues a new conversation", ana["conversation_id"] != cora["conversation_id"]))
    out.append(("the old conversation is closed to the new identity",
                ask(c, cora["conversation_id"]).status_code == 409))
    sent.clear()
    r = ask(c, ana["conversation_id"], "ana's question")
    body = r.json()
    out.append(("the new identity starts with no trace of the old one",
                r.status_code == 200 and "cora's private question" not in json.dumps(sent)
                and body["audit"]["identity"]["user_id"] == "u_ana"
                and body["audit"]["scope"]["rows"] == "region WEST only, active customers only"))

    stale = TestClient(server.app)
    stale.cookies.set(server.COOKIE, old_cookie)
    out.append(("the old session cookie no longer works", ask(stale, cora["conversation_id"]).status_code == 401))

    r = ask(c, ana["conversation_id"], user_id="u_cora")
    out.append(("a user id in the request body is ignored",
                r.status_code == 200 and r.json()["audit"]["identity"]["user_id"] == "u_ana"))

    # an answer still being prepared when the identity switches is never delivered
    gate, entered = threading.Event(), threading.Event()
    use_model(gate=gate, entered=entered)
    cora = login(c, "u_cora")
    responses: list = []
    t = threading.Thread(target=in_flight, args=(c.cookies.get(server.COOKIE), cora["conversation_id"], responses))
    t.start()
    # switch only once the agent is inside cora's turn
    entered.wait(timeout=10)
    login(c, "u_ana")
    gate.set()
    t.join(timeout=15)
    out.append(("an answer in flight across an identity switch is dropped",
                bool(responses) and responses[0].status_code == 409 and "answer" not in responses[0].json()))

    # same for a new conversation under the same identity
    gate, entered = threading.Event(), threading.Event()
    use_model(gate=gate, entered=entered)
    ana = login(c, "u_ana")
    responses = []
    t = threading.Thread(target=in_flight, args=(c.cookies.get(server.COOKIE), ana["conversation_id"], responses))
    t.start()
    entered.wait(timeout=10)
    c.post("/api/conversation")
    gate.set()
    t.join(timeout=15)
    out.append(("an answer in flight across a new conversation is dropped",
                bool(responses) and responses[0].status_code == 409))

    # what the browser receives holds nothing internal and nothing restricted
    use_model(script=["SELECT race, count(*) AS n FROM customers GROUP BY race", ("make_chart", {"mark": "bar", "x_field": "race", "y_field": "n"})])
    fern = login(c, "u_fern")
    r = ask(c, fern["conversation_id"])
    text = r.text
    with db.connect() as conn:
        ids = [row[0] for row in conn.execute("SELECT national_id FROM customers")]
    out.append(("responses hold no internal audit fields or restricted values",
                r.status_code == 200 and not any(k in text for k in INTERNAL) and not any(i in text for i in ids)))
    out.append(("the chart in the response is the server-built one", (r.json().get("chart") or {}).get("mark", {}).get("type") == "bar"))

    r = c.post("/api/session", json={"user_id": "u_ana"})
    cookie = r.headers.get("set-cookie", "").lower()
    out.append(("the session cookie is httponly and samesite strict", "httponly" in cookie and "samesite=strict" in cookie))
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
    for name, ok in results:
        print(f"{'pass' if ok else 'FAIL'}  {name}")
    bad = sum(1 for _, ok in results if not ok)
    print(f"\n{len(results) - bad}/{len(results)} server checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
