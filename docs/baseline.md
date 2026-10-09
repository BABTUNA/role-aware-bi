# Baseline backend

The agent as shipped, before any changes.

## 1. Current implementation and issues

**How it works.** `baseline.run()` looks up the user, puts their role and region in the system prompt, and runs an OpenAI tool loop. The model writes SQL and calls `run_sql(sql, role)`, choosing the role itself. `_run_sql` does one column check, runs the SQL on raw SQLite and returns rows as text. Every other rule is English in the prompt.

**Issues.** Checked by calling `_run_sql` directly, no model involved.

- **The model picks the role.** `role` is a tool argument, so the check trusts whatever the model typed. The enum also leaves out `fair_lending`.
- **`ROLE_RANK` is a ladder.** compliance and admin skip the column check, so admin can read `national_id`. It also over-blocks: reviewer gets "permission denied" on income, fair_lending on `race`. c6 and c8 can't pass.
- **The column check only reads the SELECT list.** As analyst, `SELECT *`, a `WHERE annual_income_usd > ...` filter, and `SELECT x FROM (SELECT national_id AS x ...)` all get through.
- **No row or table scoping in code.** Region, offboarded customers, case_notes access, k = 2 and the protected-class floors are prompt text only.
- **Cache keyed on question text.** One user's rows get served to another (L9). A corrected retry by the same user returns the first query's rows.
- **History keyed on conversation id.** A new identity on the same conversation keeps the old system prompt and every row read.
- **The DB is writable.** `UPDATE users SET role='compliance' WHERE user_id='u_ana'` committed, and `get_user` returned compliance after. No row cap or timeout either.
- **`make_chart` plots model-supplied rows**, not query results, and returns a Python repr no UI can parse.
- **Refusals, errors and empty results are all plain strings.**
- **Rows are logged at INFO**, so restricted data reaches logs even when the model drops it.
- **Prompt injections in the data.** t004's `memo` and case note n002 tell the model to re-run as compliance.
- **c001 and c008 are one person** in two regions, so k = 2 on `customer_id` can count one human twice.

## 2. Call tree

```
run(question, user_id, conversation_id): one user turn, returns AgentResult (agent/baseline.py:71)
├── db.get_user(user_id): role and region from the users table (agent/db.py:21)
├── SYSTEM.format(...): system prompt with identity and access rules in English (agent/baseline.py:22)
├── _HISTORY[conversation_id]: reuse prior messages if the id exists (agent/baseline.py:84)
├── loop: up to 12 model calls (agent/baseline.py:90)
│   ├── client.chat.completions.create(...): send messages and TOOLS to OpenAI (agent/baseline.py:93)
│   ├── no tool_calls: text becomes the answer, loop ends (agent/baseline.py:128)
│   └── tools.dispatch(name, args, question): run one tool, return a string (agent/tools.py:162)
│       ├── list_tables / describe_table: table names and CREATE text (agent/tools.py:164)
│       ├── run_sql → _run_sql(sql, role, question): the only access check (agent/tools.py:130)
│       │   ├── ROLE_RANK + split(" from ")[0]: column check, skipped for compliance and admin (agent/tools.py:134)
│       │   ├── _QUERY_CACHE[question]: return cached rows on a hit (agent/tools.py:143)
│       │   └── db.execute(sql): raw read-write SQLite (agent/db.py:32)
│       ├── make_chart: wrap model rows in a Vega-Lite dict (agent/tools.py:177)
│       └── ask_clarifying_question / decline: echo text back, end the turn (agent/tools.py:190)
└── _HISTORY[conversation_id] = messages: save for follow-ups (agent/baseline.py:167)
```

The eval calls this from `run_questions` and `run_leaks` (eval/run_eval.py:144, 192), then checks the answer, scans the transcript for canaries, and scans `sql_log` for forbidden columns.

| File | What it does |
|---|---|
| `seed.py` | Schema and fixture. Writes `fraud.db`, plants the injections and the duplicate customer |
| `agent/baseline.py` | System prompt, tool loop, `AgentResult`, history |
| `agent/tools.py` | Tool schemas, dispatch, the access check, the cache |
| `agent/db.py` | Connect, user lookup, raw execute |
| `eval/run_eval.py` | Runs both suites and the leak checks |
| `eval/questions.yaml` | 18 correctness cases |
| `eval/leaks.yaml` | 17 data access cases, all must pass |

## 3. Core data structures

**Database.** `region` only lives on `customers`, so scoping anything else means joining back.

```
customers ◄── transactions.customer_id ◄── alerts.txn_id ◄── case_notes.alert_id
users     ◄── case_notes.author_id
```

| Table | Notes |
|---|---|
| `users` | 6 rows: user_id, role, region |
| `customers` | 15 rows, 2 offboarded. Columns T0 to T5 per the README |
| `transactions` | 19 rows. Cents, UTC, USD/EUR/MXN |
| `alerts` | 14 rows. `status` has mixed case |
| `case_notes` | 5 rows of free text |

**Messages.** OpenAI chat format, kept in `_HISTORY`. Tool results are flattened text.

```python
{"role": "assistant", "tool_calls": [{"function": {"name": "run_sql",
    "arguments": "{\"sql\": \"SELECT count(*) n FROM customers ...\", \"role\": \"analyst\"}"}}]}
{"role": "tool", "content": "1 row(s)\nn\n6"}
```

**Tools.** `list_tables`, `describe_table`, `run_sql(sql, role)`, `make_chart(mark, x_field, y_field, rows)`, and the two that end the turn, `ask_clarifying_question` and `decline`.

**Access and state** (`agent/tools.py`).

```python
ROLE_RANK = {"analyst": 1, "fair_lending": 1, "reviewer": 2, "compliance": 3, "admin": 99}
RESTRICTED_COLUMNS = ("national_id", "dob", "email", "phone",
                      "annual_income_usd", "zip_code", "race", "ethnicity", "sex")
_QUERY_CACHE: dict[str, list[dict]]   # keyed on question text
_HISTORY: dict[str, list[dict]]       # keyed on conversation id, in baseline.py
```

**AgentResult.** What the eval reads.

| Field | Used for |
|---|---|
| `answer` | number matching |
| `transcript` | canary scan, every tool call and result as a string |
| `tool_calls` | role mismatch check |
| `sql_log` | forbidden column scan |
| `clarified`, `declined` | clarify and decline cases |
