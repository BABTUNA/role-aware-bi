# Backend

The backend as it is now. [baseline.md](baseline.md) is the same review of the code as received.

## 1. Current implementation and open issues

**How it works.** The browser picks a user, and `app/server.py` turns that into a session cookie and a server-issued conversation id. `baseline.run()` resolves the user into a `Scope` from the users table and puts that user's scoped schema in the system prompt. Then it runs the OpenAI tool loop, with gpt-5.4 by default. The model writes SQL but never names a role. Every query goes through `db.query()`:
1. an out-of-scope filter check
2. a read-only connection where each allowed table is a temp view that already filters rows and drops columns
3. an authorizer that refuses everything else
4. for anything that aggregates customers, a sqlglot plan that checks the disclosure floors on a second, server-only connection

Charts are built server-side from the last authorized result. Every turn writes an audit record, and the UI gets a sanitized copy.

**Open issues.** The full list with examples is in [limitations.md](limitations.md).

- **Multi-query differencing.** fair_lending can still isolate one person by combining three or more answers. The population record only compares two at a time.
- **In-process state.** Sessions, history and the fair_lending population record live in memory. A restart clears them, and separate processes don't share them.
- **The audit file.** It holds every row the model saw. It's owner-only, but it isn't encrypted, isn't tamper-evident, and has no retention or rotation.
- **Prompt-dependent behaviour.** The server enforces access, but whether the model calls `decline`, declines an age question (L6), or refuses to swap in a different measure all rest on the prompt. A model change can move them.
- **Fail-closed over-refusal.** Customer aggregates with CTEs, FROM subqueries or windows come back as `unsupported:`, so a fair question can end in a refusal.
- **Out-of-scope check coverage.** `region = 'EAST'` and `IN (...)` are refused, but `region <> 'WEST'` or `LIKE 'E%'` still return an empty result that reads as "none".
- **Free text.** Memos and case notes reach the roles that may read them. Injections can't change the scope, but they can steer the wording of an answer.
- **Cost of the checks.** Each customer aggregate opens a second connection and runs one or two extra queries. The scoped schema adds 600 to 750 input tokens per question.
- **The provider sees what the model sees.** Everything in `model_saw` was sent to OpenAI.

## 2. Call tree

**One chat request.**

```
chat(body, request): one question for the session's identity (app/server.py:151)
├── _current(request): session cookie to user and conversation, 401 when missing (app/server.py:74)
├── conversation check: 409 when the id isn't this session's current one (app/server.py:154)
├── baseline.run(question, user_id, conversation_id): one agent turn (agent/baseline.py:106)
│   ├── policy.scope_for(db.get_user(user_id)): role and region from the users table into a Scope (agent/baseline.py:109)
│   ├── SYSTEM.format(access=..., schema=...): prompt with the scope and the scoped schema (agent/baseline.py:119)
│   ├── history_key = (fingerprint, conversation_id): context only for the same identity and permissions (agent/baseline.py:122)
│   ├── audit.Turn(scope, question, conversation_id): start the turn's record (agent/baseline.py:139)
│   ├── loop: up to 12 model calls (agent/baseline.py:145)
│   │   ├── client.chat.completions.create(...): the model picks the next tool (agent/baseline.py:148)
│   │   └── tools.dispatch(name, args, scope, trace, last_result): run one tool (agent/tools.py:177)
│   │       ├── run_sql → _run_sql(sql, scope, trace): the only path to data (agent/tools.py:122)
│   │       │   └── db.query(sql, scope, checks): enforcement, expanded below (agent/db.py:155)
│   │       ├── describe_table / list_tables: the scoped schema only (agent/tools.py:187)
│   │       ├── make_chart → charts.build(...): spec from the last authorized result, never model rows (agent/tools.py:201)
│   │       └── decline / ask_clarifying_question: end the turn (agent/tools.py:215)
│   ├── refusal contract: a turn that ends on a server refusal is marked declined (agent/baseline.py:189)
│   └── _close_audit(turn, result): write the full record, no record means no answer (agent/baseline.py:246)
│       ├── audit.write(record): one JSON line, owner-only file (agent/audit.py:123)
│       └── audit.sanitize(record): the user's view, becomes result.audit (agent/audit.py:139)
└── stale check: 409 if the session or conversation changed during the turn (app/server.py:165)
```

**Inside `db.query`.**

```
query(sql, scope, checks): run model SQL inside the scope (agent/db.py:155)
├── disclosure.out_of_scope_filter(sql, scope): refuse a filter that can only match hidden rows (agent/db.py:165)
├── _open(scope): read-only connection, one temp view per allowed table (agent/db.py:169)
├── _execute(conn, sql, ...): authorizer, 2 s timeout, 200-row cap, tracks the tables touched (agent/db.py:172)
├── disclosure.plan(sql, scope, touched, columns): does a floor apply, and is the shape checkable (agent/db.py:174)
└── when a floor applies
    ├── _open(scope, person_key=True): server-only connection whose views also carry the person key (agent/db.py:178)
    ├── _execute(check_sql): the same query plus people and record counts per row (agent/db.py:180)
    ├── _execute(members_sql): the people in the population, never stored (agent/db.py:184)
    ├── disclosure.enforce(...): k = 2, protected-class population and cells, suppression (agent/db.py:201)
    └── disclosure.audit(...): the fair_lending population record (agent/db.py:202)
```

**Files.**

| File | What it does |
|---|---|
| `app/server.py` | FastAPI: sessions, conversation ids, `/api/users`, `/api/session`, `/api/conversation`, `/api/chat`, stale-answer checks, serves the built UI |
| `agent/baseline.py` | System prompt, the tool loop, history keyed by identity, the refusal contract, closing the audit record |
| `agent/tools.py` | Tool schemas and dispatch. `run_sql` has no role argument and `make_chart` takes no data |
| `agent/policy.py` | The permission table, `Scope`, the view SQL, the scoped schema with column notes, refusal messages |
| `agent/db.py` | The read-only connection, temp views, authorizer, limits, and the floor checks on a second connection |
| `agent/disclosure.py` | sqlglot: out-of-scope filters, floor plans, enforcement, the fair_lending population record |
| `agent/charts.py` | Builds Vega-Lite specs from authorized results only |
| `agent/audit.py` | The per-turn record, writing it, and the sanitized copy |
| `eval/` | The model eval plus `test_scope`, `test_audit`, `test_charts`, `test_server`, and `fakes.py` |

## 3. Core data structures

**Scope.** Built once per turn from the users table. Nothing the model writes can change it.

```python
Scope(user_id="u_ana", full_name="Ana Reyes", role="analyst", region="WEST", policy=POLICIES["analyst"])
Policy(tables=("customers", "transactions", "alerts"), customer_columns=T0 + T1,
       own_region_only=True, include_offboarded=False, aggregate_only=False, schema_only=())
```

**Temp views** (`policy.views`). One per allowed table, named like the real table so plain SQL resolves to the view.

```sql
CREATE TEMP VIEW customers AS SELECT c.customer_id AS customer_id, ... FROM main.customers c
  WHERE c.region = 'WEST' AND c.deleted_at IS NULL
```

**QueryResult** (`db.query`).

| Field | Holds |
|---|---|
| `rows`, `columns` | what the model is shown, after suppression |
| `truncated` | more than 200 rows matched |
| `redactions` | for example "2 of 4 cells had fewer than 3 people and were suppressed" |

**Plan** (`disclosure.plan`). Only built for queries that aggregate customers.

| Field | Holds |
|---|---|
| `check_sql` | the query plus `COUNT(DISTINCT __person)` and `COUNT(DISTINCT __record)` |
| `members_sql` | `SELECT DISTINCT __person` over the same WHERE |
| `protected_key`, `key_positions` | the race, ethnicity or sex column a breakdown groups by |

**Process state.** Every key includes the identity, and nothing is shared across users.

| Name | Key | Holds |
|---|---|---|
| `server._SESSIONS` | session cookie | `Session(user_id, conversation_id)` |
| `baseline._HISTORY` | (scope fingerprint, conversation id) | the message list |
| `baseline._OWNER` | conversation id | the fingerprint that started it |
| `disclosure._ANSWERED` | user id | (kind, set of people) per answered fair_lending query |

**Audit record** (`audit.jsonl`, one line per turn). `AgentResult.audit` and the API return the sanitized subset.

```json
{"turn_id": "...", "ts": "...", "conversation_id": "...",
 "identity": {"user_id": "u_fern", "role": "fair_lending", "region": null},
 "authority": {"rows": "all regions, active customers only", "withheld_columns": ["customer_id", "..."],
               "views": {"customers": "SELECT ..."}, "policy_fingerprint": "..."},
 "steps": [{"tool": "run_sql", "sql": "SELECT race, count(*) ...", "status": "ok", "row_count": 4,
            "redactions": ["2 of 4 cells ..."], "floor_checks": [{"check": "protected_class",
            "population": 12, "decision": "suppressed"}], "model_saw": "4 row(s) ..."}],
 "outcome": {"status": "answered", "refusal": null}, "model": "gpt-5.4",
 "tokens": {"input": 2914, "output": 85}, "latency_ms": 1900}
```

The sanitized copy drops `views`, `policy_fingerprint`, `floor_checks` and `model_saw`.
