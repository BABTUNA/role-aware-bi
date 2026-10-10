# Frontend proposal

A chat UI over `agent.baseline.run`. Written as the proposal, then built as described.

**Running it.**

```bash
pip install -r requirements.txt && python seed.py
set -a && . ./.env && set +a && uvicorn app.server:app --port 8000
```

```bash
cd web && npm install && npm run dev
```

Then open http://localhost:5173. `npm run build` puts the UI in `web/dist`, and uvicorn serves it on port 8000 directly.

**Tests.** `eval/test_server.py` (sessions, switching, answers dropped after a switch), `eval/test_charts.py` (charts only from authorized results), and `cd web && npm test` (the reducer's stale-answer guard, and refusals vs empty results).

## 1. Stack and architecture

**Stack.**

| Layer | Pick | Why |
|---|---|---|
| API | FastAPI + uvicorn | Thin layer over the existing Python agent. Sync endpoints run in a threadpool, so `baseline.run` is called as is |
| UI | React + Vite + TypeScript | Plain single-page app. No SSR needed, fast dev server, typed API contract |
| Styling | Tailwind + lucide icons | Hand-built components, no component framework to fight |
| Charts | Vega-Lite via `vega-embed` | `make_chart` already speaks Vega-Lite. The server builds the spec, the browser only renders it |
| State | React `useReducer` | One reducer for identity, conversation and the selected turn. No store library |

**How it fits together.**

- **Identity is a server session.** Picking a user calls `POST /api/session`, which sets an httpOnly cookie and returns a fresh, server-generated conversation id. `/api/chat` never takes a `user_id`. It reads the identity from the session, the same way the agent reads it from the users table and never from the model. The picker stands in for a real login.
- **Switching identity is a new session.** The old conversation is dropped on the server, and the screen is cleared too. A screen that still shows user A's answers to user B is a leak, same as a shared history.
- **Each answer renders from the sanitized audit.** `AgentResult.audit` already has the steps, their SQL, status, rows and redactions. The answer card and the "what the agent did" panel both read it, so the UI never shows data that isn't in the audit.
- **Charts bind to query results, not model rows.** Today `make_chart` plots whatever rows the model passes in. I'd change it to take only `mark`, `x_field`, `y_field` and `title`, and build the spec server-side from the last successful `run_sql` result. A chart can then only show audited, in-scope data.

**Screen.**

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Ana Reyes · analyst · WEST  ▾      scope: WEST, active · 10 of 19 columns│
├───────────────────────────────────────────┬──────────────────────────────┤
│  thread                                   │  What the agent did          │
│  ─ you: open alerts by rule, chart it     │  identity + scope used       │
│  ─ agent: answer text                     │  1 run_sql  ok  4 rows       │
│      [table]  [chart]                     │    SELECT rule_id, ...       │
│  ─ you: and only the high severity ones?  │  2 make_chart  bar           │
│  ─ agent: ...                             │  outcome: answered · 2.3 s   │
│  [ ask a question ...               send ]│                              │
└───────────────────────────────────────────┴──────────────────────────────┘
```

**Outcomes look different.**

| Outcome | Comes from | Looks like |
|---|---|---|
| Answered with rows | `outcome.status = answered` | Answer text, then table and chart |
| Empty result | an `ok` step with `row_count = 0` | Neutral "no matching rows" plus the scope it searched ("in WEST, active customers") |
| Access denied | `outcome.refusal` starting with `access denied:` | Amber card with a lock icon. Shows the server's reason, not the model's prose, plus the generalized column on offer when there is one ("use zip3") |
| Unsupported shape | refusal starting with `unsupported:` | Grey info card, "couldn't check this query, try rephrasing" |
| Clarifying question | `outcome.status = clarified` | The question set apart as a prompt to reply to |
| Suppressed cells | `redactions` on a step | Cells shown as `<3` with a tooltip, and a note under the table |
| Error | `outcome.error` | Plain error line, nothing else |

**What I'd leave off the screen.** The raw audit file, view SQL and policy internals, the system prompt, regenerating or editing answers, a list of saved conversations, and real login.

**Build order and cut lines.**
1. FastAPI layer with sessions, `/api/users`, `/api/session`, `/api/chat`.
2. Thread, identity picker, reset on switch, outcome cards.
3. "What the agent did" panel.
4. Tables, then charts bound to query results.
5. Suggested questions per role, empty states, narrow-screen layout.

*Cut line: below here only if time allows.*

6. Streaming steps live over SSE, so the panel fills in while the agent works.

## 2. Request flow

**One chat turn.**

```
Composer.onSubmit(question): send the question for the current session (web/src/components/Composer.tsx)
└── api.chat(conversationId, question): POST /api/chat, cookie carries the session (web/src/api.ts)
    └── chat(req, session): resolve identity from the session, never from the body (app/server.py)
        ├── sessions.get(cookie): session id to user_id and conversation id, 401 when missing (app/server.py)
        ├── check conversationId belongs to this session, otherwise 409 and the UI starts fresh (app/server.py)
        ├── baseline.run(question, user_id, conversation_id): the existing agent turn (agent/baseline.py)
        │   ├── tools.dispatch(...): run_sql under the scope, make_chart bound to the last result (agent/tools.py)
        │   └── _close_audit(turn, result): full record server-side, sanitized copy on result.audit (agent/baseline.py)
        └── ChatResponse.from_result(result): answer, outcome, refusal, context_reset, audit (app/server.py)
└── reducer("turn_done"): append the turn, select it in the panel (web/src/state.ts)
    ├── AnswerCard: picks the outcome style from the table above (web/src/components/AnswerCard.tsx)
    │   ├── ResultTable: rows of the step the answer used (web/src/components/ResultTable.tsx)
    │   └── Chart: vega-embed on the spec from the make_chart step (web/src/components/Chart.tsx)
    └── ActivityPanel: identity, scope, steps, outcome from audit (web/src/components/ActivityPanel.tsx)
```

**Switching identity.**

```
IdentityPicker.onChange(user_id): ask for a new session (web/src/components/IdentityPicker.tsx)
└── api.startSession(user_id): POST /api/session (web/src/api.ts)
    └── start_session(user_id): drop the old session, new cookie, new conversation id (app/server.py)
└── reducer("identity_switched"): clear the thread and the panel, show the new scope (web/src/state.ts)
```

**Planned files.**

| File | What it does |
|---|---|
| `app/server.py` | FastAPI app: sessions, the four endpoints, serves the built UI |
| `agent/tools.py` | `make_chart` change: no `rows` argument, spec built from the last result |
| `web/src/state.ts` | Reducer for identity, conversation, turns, selection |
| `web/src/api.ts` | Typed fetch client, cookies included |
| `web/src/types.ts` | API and audit types, kept in step with `agent/audit.sanitize` |
| `web/src/components/*` | IdentityPicker, ScopeChip, Thread, AnswerCard, ResultTable, Chart, ActivityPanel, Composer, SuggestedQuestions |
| `.claude/launch.json` | Dev server config for the preview |

## 3. Data structures

**Session (server memory).**

```python
{"session_id": "s_9f2c...", "user_id": "u_ana", "conversation_id": "c_41ab..."}
```

**API.**

```
GET  /api/users      -> [{"user_id": "u_ana", "full_name": "Ana Reyes", "role": "analyst", "region": "WEST"}, ...]
POST /api/session    {"user_id": "u_rae"} -> {"identity": {...}, "scope": {...}, "conversation_id": "c_..."}
POST /api/chat       {"conversation_id": "c_...", "question": "..."} -> ChatResponse
GET  /api/scope      -> the current session's scope, same shape as audit.scope
```

**ChatResponse.** Mostly `AgentResult.audit` passed through, plus the chart spec.

```json
{
  "answer": "There are 5 open alerts in WEST.",
  "outcome": {"status": "answered", "refusal": null, "context_reset": null, "error": null},
  "audit": {
    "turn_id": "6f8f...",
    "identity": {"user_id": "u_ana", "role": "analyst", "region": "WEST"},
    "scope": {"rows": "region WEST only, active customers only", "withheld_columns": ["zip_code", "..."]},
    "steps": [
      {"tool": "run_sql", "status": "ok", "sql": "SELECT count(*) AS n FROM alerts WHERE status = 'open'",
       "columns": ["n"], "rows": [[5]], "row_count": 1, "truncated": false, "redactions": []}
    ],
    "latency_ms": 2310
  },
  "chart": null
}
```

**UI state.**

```ts
type State = {
  identity: Identity | null      // from /api/session, never edited client-side
  scope: Scope | null
  conversationId: string | null  // server-issued, replaced on every switch
  turns: Turn[]                  // question + ChatResponse, cleared on switch
  selectedTurn: string | null    // which turn the panel shows
  pending: boolean
}
```
