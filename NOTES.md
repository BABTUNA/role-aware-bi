# NOTES

Longer write-ups: [baseline review](docs/baseline.md), [frontend](docs/frontend.md), [known limitations](docs/limitations.md), [AI log with every prompt](docs/ai-log.md).

## 1. Scorecard

`python eval/run_eval.py` with the default model (`gpt-5.4`), exit 0:

```
  correctness + calibration   20/20  (100%)
  data access                 20/20  CLEAN
```

| Suite | Result |
|---|---|
| Eval | 20/20 correctness (18 original plus g1, g2), 20/20 leaks (17 original plus L18 to L20) |
| Five more full runs per model | gpt-5.4 and gpt-5.5 both 20/20 and 20/20 on every run |
| Offline: `test_scope`, `test_audit`, `test_charts`, `test_server`, web vitest | 97/97, 6/6, 10/10, 13/13, 14/14 |

The baseline scored 11/18 and 12/17.

**What the number doesn't cover.** It's 40 hand-written questions over 15 customers. The number check passes if the value appears anywhere in the answer, and the leak check only looks for strings and column names, which is how the original L9 passed while leaking region counts. There are few multi-turn cases and no UI cases. Some behaviour still rests on the prompt, like calling `decline` at all, so a model change can move it. The data boundary doesn't rest on the prompt: across 774 benchmark turns on four models, no restricted value reached a model.

## 2. What I found

| Finding | In the eval? |
|---|---|
| The model chose its own role, and `ROLE_RANK` was a ladder with admin at 99 | Yes |
| The column check only read the SELECT list, so `SELECT *`, WHERE filters and subqueries got through | Partly |
| Rows were only scoped in the prompt | Yes |
| The cache was keyed on question text, so one user's rows went to another | Yes, but L9 passed while leaking |
| History was keyed on conversation id only, so a new identity kept the old context | No |
| The DB was writable: `UPDATE users SET role='compliance'` stuck | No |
| `make_chart` plotted rows the model made up | No |
| Every result row was logged | No |
| c001 and c008 are one person, so k = 2 on records can describe one human | No, I added L20 |
| fair_lending can difference two answers into one person's race or income | No, I added L18 and L19 |
| A plain `EXISTS` filter is a yes/no oracle for a role that can't read rows | No |
| Out-of-scope filters returned a 0 that looked like an answer | No |

**Unfixable here.** Differencing across three or more queries still works: four income sums, each pair 2 people apart, give c005's exact income. Stopping it needs a query audit or noise on answers. Free text in memos and case notes can still steer an answer's wording, though not the data it reaches. Whatever the model sees also goes to the model provider.

**Brief versus eval.** The brief ([INSTRUCTIONS.md](INSTRUCTIONS.md)) says an analyst asking for age gets `birth_year`, but L6 expects a decline. I made it decline the computed age and offer `birth_year`.

## 3. What I deliberately did not do

- **Real login.** The identity picker stands in for it, and the server treats the choice as a session.
- **A query audit or answer noise** for multi-query inference.
- **General SQL rewriting.** The floor checks accept what sqlglot can check exactly and refuse the rest. The SQLite views and authorizer stay the boundary.
- **Entity resolution beyond exact `national_id`,** and deduplicating answers. Only the floors count people.
- **Filtering free text for injections.** The server already makes them powerless over data.
- **Deployment pieces:** encrypted or tamper-evident audit storage, a persistent session store, a result cache, rate limits, and a Postgres row-level-security port.
- **UI extras:** streaming, editing answers, saved conversations.

## 4. Audit record

Each turn appends one JSON line to `audit.jsonl` (`agent/audit.py`). It holds:
- the identity
- the resolved permissions, with the view SQL that applies them
- every tool call, with its SQL, status, refusal reason, row count, truncation, redactions, a floor-check summary, and `model_saw`, the exact text the model got
- the outcome, tokens and latency

That's where "what did the agent see, on whose authority" gets answered. Every exit writes a record, crashes included, and if the write fails the answer is withheld. The people behind a floor check are national ids, so only their count is kept. The UI gets a sanitized copy. The file is as sensitive as the warehouse and isn't tamper-evident.

## 5. Cost and latency

Five full eval runs per model, 215 turns each, all run at the same time on the current prompt:

| Model | Correct | Leaks | p50 s | p95 s | Tokens in / out | Tool calls | $ / question | $ p95 | Full eval |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.5 | 5 of 5 at 20/20 | 5 of 5 at 20/20 | 2.8 | 6.4 | 2,863 / 164 | 1.22 | $0.0192 | $0.0345 | $0.83 |
| **gpt-5.4** (default) | 5 of 5 at 20/20 | 5 of 5 at 20/20 | 1.9 | 4.0 | 2,914 / 85 | 1.29 | $0.0086 | $0.0143 | $0.37 |

On the earlier prompt (two runs each), the smaller models failed:

| Model | Correct | Leaks | $ / question |
|---|---|---|---|
| gpt-5.4-mini | 17, 16 | 19, 19 | $0.0020 |
| gpt-5.4-nano | 16, 12 | 19, 20 | $0.0005 |

Their leak failures were missed `decline` calls, not data. They never saw restricted rows, but the gate counts the missing decline.

Prices are OpenAI's per million tokens: gpt-5.5 $5 in and $30 out, gpt-5.4 $2.50 and $15. The dollars are an upper bound, since cached input isn't counted. SQL is about 0.1% of a turn's time.

**Getting gpt-5.4 there.** It failed c4 by asking for a date range the question didn't need, and u2 by asking instead of declining. Three general prompt changes fixed it:
- a rule for asking versus declining
- the user's scoped schema in the prompt, with notes on what each column measures
- a status note that stops pointing it at questions the data can't answer

None names an eval case or touches the server checks. The schema adds 600 to 750 input tokens, but it saves `describe_table` calls.

**Tradeoff.** gpt-5.4 costs 45% of gpt-5.5 and is about a third faster, and it matched it on 6 of 6 runs. Going back is one line in `agent/baseline.py`.

**At 100× the questions** (about $0.86 per 100 on gpt-5.4), the in-process state breaks first. Sessions, history and the fair_lending population record don't survive a restart or scale across processes. The audit file needs a single writer. Each turn holds a server thread for 2 to 4 s, so throughput is set by the thread pool and the OpenAI rate limits.

**At 100× the rows,** SQLite is fine, but the 200-row cap trips more often and bigger results cost more tokens. At warehouse scale, the views and authorizer become the warehouse's own row and column security, and the sqlglot floor checks stay.

## 6. AI log

Built with Claude Code over one session of 28 prompts, every one listed word for word in [docs/ai-log.md](docs/ai-log.md).

**I overrode it:**
- I deferred the k = 2 floor until identity and the authorizer were right.
- I put the floors before isolation.
- I ruled out a general SQL rewriter.
- I stopped the security work at two-query differencing.
- I made the UI get a sanitized audit record.
- I required checking exit codes and stderr instead of trusting summaries.
- I had it fix gpt-5.4 rather than settle for gpt-5.5.

**It was wrong:**
- Its first authorizer blocked its own views.
- It proposed a fair_lending filter rule that would have been an oracle, and caught that before shipping.
- Three of its prompt notes misled the models: "keep it short" broke t3, a status note made gpt-5.4 ask instead of decline, and a column-matching rule made gpt-5.4 answer "credit score" with `risk_score`.
- It committed a test file that crashed on start and reported it as passing.
- It ran a secrets scan that read zero files.

Exit-code checks and two review agents caught most of these.

**The agent model was wrong in the baseline:** gpt-5.5 claimed `admin` or `compliance` whenever it was refused, answered "0 yesterday", added EUR to USD, and missed the mixed-case alert statuses.

## 7. The interface

Needs Python 3.10+ and Node 20.19+. Tested from a fresh clone:

```bash
pip install -r requirements.txt && python seed.py
cp .env.example .env    # then add your key
set -a && . ./.env && set +a && uvicorn app.server:app --port 8000
cd web && npm install && npm run dev    # http://localhost:5173
```

**On screen:**
- An identity picker. Switching starts a new session and conversation, clears the thread, panel and draft, and drops any answer still in flight.
- A thread with follow-ups, tables, and charts the server builds from the last authorized result. Suppressed cells show as `<3` and stay off charts.
- Refusals, empty results, clarifying questions and errors each look different.
- A "What the agent did" panel: who it ran as, the permissions, every query and its status, refusals, redactions and timing.

**Left off:** the raw audit, view SQL, the system prompt, streaming, editing answers. Checked at 320 to 1920 px and by keyboard.

## 8. Walkthrough

Recording: *(link)*.
