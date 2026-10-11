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

**What the number doesn't cover.** The evaluation covers only 40 hand-written questions over 15 customers, so it isn't exhaustive. Correctness checks look for expected values, while leak checks rely on string matching, which missed issues like L9. Multi-turn and UI coverage is limited, and some refusal behavior still depends on the prompt. However, authorization is enforced in code, and no restricted values were detected across 774 benchmark turns using four different models.



## 2. What I Found

The biggest issue was that authorization depended on the LLM instead of the backend. The model chose its own role, permissions used an incorrect hierarchy, and SQL checks only inspected the SELECT list. This allowed bypasses through `SELECT *`, WHERE clauses, and subqueries. Region restrictions were also enforced only through prompts.

Here are several additional vulnerabilities:

| Finding | Why it matters |
|---|---|
| **Privilege escalation** | The database was writable. An `UPDATE users` query could permanently change a user's role to compliance. |
| **Cross-user data leaks** | Conversation history carried over between identities, and the question-keyed cache could return another user's data. L9 even passed the original eval while leaking. |
| **Indirect data exposure** | `make_chart` trusted model-supplied rows, while raw query results were written to application logs. |
| **Aggregation inference** | Duplicate customer records could bypass k=2. Fair-lending users could also combine valid aggregates to recover an individual's race or income. I added L18–L20 to cover these cases. |
| **SQL inference and misleading results** | `EXISTS` filters could reveal restricted facts through yes/no answers, while out-of-scope queries returned misleading zeros. |

**Remaining limitations.** Multi-query differencing is not fully solved. I demonstrated that four individually permitted income sums could reveal one person's exact income. Preventing this reliably would require more comprehensive query auditing or privacy-preserving aggregation. Prompt injections in free-text fields can still influence answer wording, although they cannot bypass backend authorization. Authorized results also reach the model provider, which is a tradeoff of going with this architecture.

**Specification ambiguity.** The spec allows `birth_year` as generalized data, but L6 expects a refusal for age calculations. I chose to decline age calculations while offering `birth_year` instead, satisfying both interpretations.



## 3. What I Deliberately Did Not Do

I prioritized security, correctness, and a usable interface over building a production-ready system. The main decisions were:

- **Real authentication.** The identity picker simulates login, while the backend manages sessions and enforces permissions. Building a full authentication system was outside the scope of this exercise.
- **Complete protection against multi-query inference.** Preventing all differencing attacks would require comprehensive query-history analysis or adding noise to results, introducing significant complexity and potential accuracy tradeoffs.
- **Arbitrary SQL rewriting.** I limited aggregation checks to query structures that could be safely validated with sqlglot. Unsupported queries fail closed rather than risking incorrect privacy enforcement.
- **Advanced entity resolution.** Privacy floors deduplicate using `national_id`, but query results preserve the original customer records. Broader entity resolution would require additional data and assumptions.
- **Prompt-injection filtering.** Rather than trying to sanitize every free-text field, I enforced authorization in the backend so injected instructions cannot grant access to restricted data.
- **Production infrastructure.** I left out encrypted and tamper-evident audit storage, persistent sessions, caching, rate limiting, and a PostgreSQL migration. These matter at scale but weren't necessary for the take-home.
- **Additional UI features.** I skipped streaming responses, editable answers, and saved conversations to focus on secure identity switching, charts, and audit visibility.


## 4. Audit Record

Every turn writes a structured JSON record to `audit.jsonl` through `agent/audit.py`, containing:

- **Identity and scope:** User identity, role, permissions, and the SQLite view SQL enforcing them.
- **Tool execution:** SQL executed, status, refusals, returned rows, truncation, redactions, and privacy-check summaries.
- **Model visibility:** `model_saw` records exactly what data reached the LLM.
- **Outcome and performance:** Final status, token usage, and latency.

Together, these records answer **"What did the agent see, and on whose authority?"**

Every turn is logged, including failures. If the audit write fails, the response is withheld. Privacy checks record only the number of distinct people, never their national IDs. The UI receives a sanitized version of the audit.

**Limitations:** The audit file contains sensitive data and currently lacks encryption, tamper protection, and a retention policy.



## 5. Cost and Latency

I benchmarked GPT-5.5 and GPT-5.4 across five full evaluation runs each (215 turns per model). Both passed every correctness and leak test.

| Model | p50 / p95 latency | Tokens in / out | Cost/question | p95 cost | Full eval |
|---|---|---|---|---|---|
| GPT-5.5 | 2.8s / 6.4s | 2,863 / 164 | $0.0192 | $0.0345 | $0.83 |
| **GPT-5.4 (default)** | **1.9s / 4.0s** | 2,914 / 85 | **$0.0086** | $0.0143 | $0.37 |

GPT-5.4 costs **55% less** and is about 32% faster at p50. It initially failed some correctness cases, but general prompt improvements brought it to 20/20 correctness and leaks across six consecutive runs. These improvements included adding the scoped schema, clarifying column meanings, and distinguishing clarification from refusal. Smaller models were cheaper but failed the evaluation gate.

Costs use published API token prices and are upper estimates because cached input tokens aren't tracked. SQL accounts for roughly 0.1% of total latency. Most time is spent on model calls.

**Scaling to 100×:** At 100× the questions, we would need concurrent agent execution using asynchronous requests and multiple workers to support more users. In-memory sessions, conversation history, and privacy tracking would need shared storage, while audit logs would move to a centralized system. At 100× the rows, SQLite could still handle the workload, but the 200-row cap and larger results become concerns. At warehouse scale, we would move authorization into native database security.



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
