"""HTTP API for the chat UI

identity is a server session, picking a user here stands in for logging in
/api/chat never takes a user id, it reads the identity from the session cookie
the server issues the conversation id and replaces it on every switch, and an answer computed
for a session or conversation that ended in the meantime is never delivered

    uvicorn app.server:app --reload
"""

import logging
import os
import secrets
import threading
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import audit, baseline, db, policy

log = logging.getLogger("app.server")

COOKIE = "bi_session"
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")

# starting points shown on an empty thread, one set per role
SUGGESTIONS = {
    "analyst": [
        "How many customers are in my region right now?",
        "Break down the alerts in my region by rule and chart it",
        "What was the total value of ACH transactions in US dollars in March 2026?",
        "Which customers in my region have a risk score above 70?",
    ],
    "reviewer": [
        "What is the average annual income of customers in my region?",
        "Summarise the case notes on the open alerts in my region",
        "Which wire transfers in my region have been alerted on?",
    ],
    "compliance": [
        "How many customers are there in each region? Chart it",
        "Which customers have been offboarded, and when?",
        "Do any customers share a national id?",
    ],
    "fair_lending": [
        "Company-wide customer count broken down by sex",
        "Company-wide customer count broken down by race",
        "Average annual income by segment, as a chart",
    ],
    "admin": [
        "Which users have access, and with what roles?",
        "What tables are in the warehouse?",
    ],
}


@dataclass
class Session:
    user_id: str
    conversation_id: str


_SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()

app = FastAPI(title="role-aware BI")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def _current(request: Request) -> tuple[str, Session]:
    sid = request.cookies.get(COOKIE)
    with _LOCK:
        session = _SESSIONS.get(sid) if sid else None
    if session is None:
        raise HTTPException(401, "no active session, pick an identity first")
    return sid, session


def _session_body(session: Session) -> dict:
    scope = policy.scope_for(db.get_user(session.user_id))
    return {
        "identity": {
            "user_id": scope.user_id,
            "full_name": scope.full_name,
            "role": scope.role,
            "region": scope.region,
        },
        "scope": audit.public_scope(scope),
        "conversation_id": session.conversation_id,
        "suggestions": SUGGESTIONS.get(scope.role, []),
    }


@app.get("/api/users")
def users() -> list[dict]:
    """the identities the picker offers"""
    with db.connect() as conn:
        rows = conn.execute("SELECT user_id, full_name, role, region FROM users ORDER BY rowid").fetchall()
    return [dict(r) for r in rows]


class SessionRequest(BaseModel):
    user_id: str


@app.post("/api/session")
def start_session(body: SessionRequest, request: Request, response: Response) -> dict:
    """act as a user: ends any current session and starts a fresh conversation"""
    try:
        db.get_user(body.user_id)
    except RuntimeError:
        raise HTTPException(404, "no such user")
    old = request.cookies.get(COOKIE)
    sid = _new_id("s")
    session = Session(body.user_id, _new_id("c"))
    with _LOCK:
        if old:
            _SESSIONS.pop(old, None)
        _SESSIONS[sid] = session
    response.set_cookie(COOKIE, sid, httponly=True, samesite="strict", path="/")
    return _session_body(session)


@app.get("/api/session")
def get_session(request: Request) -> dict | None:
    """the current session, or null before an identity is picked, which isn't an error"""
    with _LOCK:
        session = _SESSIONS.get(request.cookies.get(COOKIE) or "")
    return _session_body(session) if session else None


@app.post("/api/conversation")
def new_conversation(request: Request) -> dict:
    """same identity, fresh conversation"""
    _, session = _current(request)
    with _LOCK:
        session.conversation_id = _new_id("c")
    return _session_body(session)


class ChatRequest(BaseModel):
    conversation_id: str
    question: str = Field(min_length=1, max_length=2000)


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request) -> dict:
    sid, session = _current(request)
    if body.conversation_id != session.conversation_id:
        raise HTTPException(409, "this conversation is no longer active")
    user_id, conversation_id = session.user_id, session.conversation_id
    try:
        result = baseline.run(body.question, user_id, conversation_id)
    except Exception:
        log.exception("agent turn failed")
        raise HTTPException(500, "the agent failed on this question")

    # the identity or conversation may have changed while the agent worked
    # an answer for the old one is never delivered
    with _LOCK:
        current = _SESSIONS.get(sid) is session and session.conversation_id == conversation_id
    if not current:
        raise HTTPException(409, "the session changed while this answer was being prepared")

    view = result.audit
    outcome = view["outcome"] if view else {
        "status": "error", "answer": "", "refusal": None, "error": result.error, "context_reset": None,
    }
    charts = [s["chart"] for s in (view or {}).get("steps", []) if s["tool"] == "make_chart" and s.get("chart")]
    return {
        "conversation_id": conversation_id,
        "answer": result.answer,
        "outcome": outcome,
        "audit": view,
        "chart": charts[-1] if charts else None,
    }


# the built UI, when there is one, served from the same origin as the API
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
