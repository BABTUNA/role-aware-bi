# AI log

I built this with Claude Code (Opus) in one long session. Below are my prompts in order, word for word, then where I overrode the assistant and where the models got things wrong. The full conversation is in [transcript.md](transcript.md). The agent itself runs on gpt-5.5.

## My prompts

Word for word, typos included, taken from the session log. The conversation around them is in [transcript.md](transcript.md).

1. @""
   new take home review and tell me what it's all about
2. ok let's start by doing the following make a docs folder in which we will put a md that covers the folllowing: break it down into 3 sections 1) the overall current backend implmentation as of right now and some of the major issues/concerns with it (in bullet points) 2) the function tree trace call of the essential core logic on the right side of the tree put a short description on what each of the functions calls does along with the file name  (within this section also list out all the relveatn files with a short blurb on what they do). Finally on the 3) section show me the core essentional data structures this codebase uses
3. clean up the function tree trace the function explaination should go on the right side immiedatlye of the funciton clal and the file reference should immiediatley follow (should all go in the same line)
4. also the overall md is bit too long right condense to it's essential parts
5. git init and commit the baseline (make this is a public repo
6. actually just so htat I can keep the more essentive md on how the whole repo wrosk make another verison of the md that continas the original longer description of how this works
7. yes commit and push it and after that start running the evulation metrics to see where everything currently stands
8. make a .env example so that I can copy and paste (and also have to push to the repo)
9. done, run the eval
10. first let's tackle correcting the persmission:
   Move authorization into the backend: Resolve identity and permissions server-side, independent of the LLM.
   
   idenitty needs to be moved to the server side. Also the fact that an LLM decides it make no sense. What are a couple of approaches to fix this ?
11. ok so you want get the identity associated iwth the session , scope wiht an SQL lite auhotoirzer to  blocked autorhozized users that seems fine. Keep a note of the k = 2 floor issue for later for now, that will be tackeled on later
12. yes commit and push it
13. ok now let's do the following:
   Secure SQL execution: Enforce table, column, row, and aggregation restrictions, including nested queries and filters.
   
   Isolate users: Scope caches and conversations by identity and permissions.
   
   How can esnure the SQL execution remains secure and how can we isloate user scopes in this context ?
14. do the remaining security fixes, but I'd change the order a bit.
   
   for starters, do the  resource limits, then prioritize aggregation floors since L3, L14, and L17 are required to pass. After tha, handle user isolation and out-of-scope filters.
   
   For aggregaton, I woldn't try to support arbitrary SQL rewriting. Use sqlglot for queries we can safely validate, and fail close on complex cases where we can't guarantee corectness. Make sure we don't accidentally block vald transaction or alert aggregates.
   
   Keep the SQite views and autorizer as the main security boundary. Add tests for the new cases and rerun both eval suies. Document any reaining limitations in NOTES.md.
15. Let's fix L6 with the targeted prompt change and also update  the README ambiguity in NOTES. also adress t1's case sensitivity and investigate b1-b3 to improve correctness.
   
   Rerun the full eval and confirm the leak gate is 17/17If everything looks good, commit the backend changes.
16. go aheadand push
17. Before moving to the frontend, let's reiew L6's spec ambiguity  cross-query differencing, duplicate customer identities and unsupported SQL patterns.
   
   For each one explain the risk and whether it's worth fixing   and the simplest safe approach. Prioritize correctness and security without overengineering. Don't implement changes yet.
18. Let's do all four in that order the unsupported SQL fixes and person-level counting seem worth also and the fair_lending differencing leak is significant enough to address
   
   Keep the changes minimal and make sure the population tracking doesn't introduce new correctness issues Add adversarial tests for the remaining differencing bypasses where possible.
   
   Rerun all evals and confirm we still have 17/17 leaks and 18/18 correctness document any remaining limitations in NOTES don't commit yet.
19. Looks good, let's stop expanding backend security for now the remaining multiq uery inference issue can stay documented as a known limitatin
   
   cmmit these changes locally, then verify the audit logging meets the spec   after that let's focus on the frontend
20. Yes, let's implement audit logging first. Use strutured perturn jsnol records with the identity, resolved permissionsSQL executed, results the model saw, redactions, and outcome. Keep the full audit server-side since it contains sensitive data. AgentResult.audit should expoe a sanitized version for the frontend, not raw internal records. on a side note make sure audit logging doesn't leak restricted data or break existing behavior. Add tets, rerun the evals, and document storage/security limittions in notes don't push yet
21. ok before we start on the frontend let's just summarize everything we've covered so far (short and concise)
22. Looks good. Let's move to the frontend now prioritize a polished conversational UI with identity switching follow-up questions, tables, and charts. add a "wht the agent did" panel using AgentResult.audit to show executed SQL, permissions, and refusals. also make sre switching users resets the conversation properly and that access denials look different from empty results keep thUI clean and intuitive. Before implementing, give me a short proposal for the frontend stack and architecture. Don't code anythign out yet instead make a frontend md similar to the md format we made to explain the repo when we first explored it
23. Looks good, let's build it in that order two things to watch: make sure old API responses can't show up after switching identities, and charts only use authorized query results, respecting suppression and truncation keep the UI polished but simple, especially the chat, tables, charts, and audit panel. Prioritize functionality over extra features, and add tests for identity switching and chart security.
24. Looks good. Fix the mobile identity button wrapping, then run all tests one more time and check the actual exit codes and stderr. Also spin up a couple of frontend review agents to verify the site works across various screen sizes and the UI/button don't feel off
   
   Also review the diff for secrets or accidentally tracked audit files if everything passes, commit locally but don't push yet.
25. push it
26. Let's review NOTES.md against every deliverable in the README, especially the AI log, cost and latency metrics, known limitations, andwhat we deliberately left ou
   
   collect the actual performance numbers and make sure the app can run from a fresh setup. Then give me a sht walkthrough script covering the architecture, role switching, security enforcement, charts, and audit panel
27. Before finalizing notes let's benchmark GPT-5.5, GPT-5.4, GPT-5.4 Mini, and GPT-5.4 Nano.
   
   Run the same eval suite for each model without changing prompts or security policies. Compare correctness, leaks, latency, token usage, cost per question, and tool calls.
   
   kep GPT-5.5 as the baseline and don't change the default yet I want to see whether a cheaper model can maintain the same qualty, especially the 20/20 leak gate report the results in a table and recommend the best cost/performane ption
28. Let's see if we can get GPT-5.4 to match GPT-5.5's reliability at a lower cost. plz investigate the c4 and u2 failures and make minimal, generalizable prompt improvements without hardcoding eval cases or weakening security. Then run at least 5 full evals to check consistency. also compare correctness, leaks, latency, and cost against GPT-5.5. Keep 5.5 as the default unless 5.4 consistently passes both suites.
   
   after that, finalize notes.md with the benchmark results tradeoffs and ai log.
29. yes commit and push it
30. ok I will make the script and record the video myself. What's left in this assignment
31. close the running server for now
32. Create a concise architecture diagram for my role-aware conversational BI system, focusing on the essential components: **React frontend → FastAPI (server-side identity and sessions) → LLM agent (SQL generation) → Security enforcement (SQLite scoped views, authorizer, read-only access, and sqlglot aggregation privacy checks) → SQLite database**. Show how authorized results flow back to the agent and UI, with charts generated only from authorized query results. Include a separate audit logging component that records identity, permissions, executed SQL, returned rows, and redactions. Emphasize that **the LLM never controls permissions**, restricted data is blocked before reaching the model, and unsafe queries fail closed. Keep the diagram minimal and easy to explain in under one minute. use the following arch-diagram skill
33. commit and push it (make sure that it's in the readme)
34. looks like the readme is missing context on how t run the fronted
35. > (pasted)
   > benba@MacBook-Pro-8 takehomeproblem % set -a && . ./.env && set +a
   > uvicorn app.server:app --port 8000
   >
   > zsh: command not found: uvicorn
   > benba@MacBook-Pro-8 takehomeproblem %
36. oh wait I just realized the original readme had the instructions. Go ahead and put the original readme content into an instructions md and make the readme dedicated to the things we implemented/dicussed
37. make a backend md file simlarily structured to the baseline md in the 3 section format we talked aobut
38. push it
39. > (pasted)
   > 2. Walk through an actual request
   > Suppose Ana is an analyst assigned to the WEST region.
   > She asks:
   > "What's the average risk score of customers in my region?"
   >
   > Step 1 — FastAPI establishes identity
   > FastAPI receives the request using Ana's session cookie.
   > The backend resolves her identity and permission scope:
   > User: Ana
   > Role: analyst
   > Region: WEST
   >
   > Allowed:
   > - Active WEST customers
   > - T0 and T1 columns
   >
   > Not allowed:
   > - EAST customers
   > - Deleted customers
   > - Precise identifiers
   >
   >
   > Crucially, the browser and LLM cannot arbitrarily change Ana's role.
   > Step 2 — The LLM generates SQL
   > The LLM receives the question, its instructions, and the schema it is allowed to work with.
   > It generates something like:
   > SELECT AVG(risk_score)
   > FROM customers;
   >
   >
   > Notice that there's no WHERE region = 'WEST'.
   > That's actually fine!
   > Your security architecture does not depend on the LLM remembering to filter by region.
   > Step 3 — SQLite automatically enforces Ana's permissions
   > Your backend creates a temporary customers view scoped to Ana.
   > Conceptually, it behaves like:
   > CREATE TEMP VIEW customers AS
   > SELECT customer_id, full_name, region,
   >        segment, risk_score, birth_year
   > FROM main.customers
   > WHERE region = 'WEST'
   >   AND deleted_at IS NULL;
   >
   >
   > When the LLM queries customers, SQLite resolves that name to Ana's scoped view.
   > So even without a WHERE clause in the generated SQL, the LLM can only query active WEST customers.
   > The SQLite authorizer also blocks attempts to bypass those views and access the underlying tables directly.
   > Step 4 — sqlglot checks aggregate privacy
   > Even though Ana can access risk_score, an average across one customer would reveal that customer's exact score.
   > Your disclosure layer parses the SQL and checks how many distinct people contribute to the aggregate.
   > - 1 person → refuse.
   > - 2 or more people → permitted under the standard customer aggregate floor.
   > Fair Lending has additional rules for protected-class reporting.
   > These checks happen server-side, without revealing restricted data to the LLM.
   > Step 5 — The database returns authorized results
   > Let's say the average is 58.4.
   > The tool returns something like:
   > {
   >   "columns": ["avg_risk_score"],
   >   "rows": [[58.4]]
   > }
   >
   >
   > The LLM receives that result and generates the response:
   > "The average risk score for active customers in WEST is 58.4."
   >
   > If the query was refused, the model receives a refusal instead of the restricted result.
   > Step 6 — The backend records an audit trail
   > For this turn, your system records:
   > - Ana's identity, role, and resolved permissions.
   > - The SQL the LLM submitted.
   > - Which security checks applied.
   > - The results actually returned to the LLM.
   > - Any refusals, suppression, or redactions.
   > The full record remains server-side. A sanitized version powers the frontend's "What the agent did" panel.
   
   
   
   immeidately in after the archeicture diaram in the readme put  a similar logic trace to the one above (but shorter)
40. modify the right side of the what the agent did tab so that it's collapsible
41. are we currently saving the logs of the chats (on the UI) as audits if so where ?
42. push it
43. made some changes to the note.md svae and push
44. rewrite the 
   
   
   
   > (pasted)
   > 6. AI log
   > Built with Claude Code over one session of 28 prompts, every one listed word for word in docs/ai-log.md.
   >
   > I overrode it:
   
   
   
    so that it's shorter and also add a raw conversation logs for our entire chat

## Where I overrode the assistant

| What it proposed | What I did instead | Why |
|---|---|---|
| Build the k = 2 floor together with server-side identity | Deferred it | Get identity and the authorizer right first, then floors on top |
| Isolation before aggregation floors | Resource limits, then floors, then isolation and out-of-scope filters | L3, L14 and L17 were failing the gate |
| A general rewrite of model SQL for the floor checks | Only shapes sqlglot can check exactly, refuse the rest, views and authorizer stay the boundary | A rewriter is where silent mistakes hide |
| Keep going on fair_lending inference (three-query differencing) | Stopped and documented it | Diminishing returns against the rest of the deliverables |
| Return the raw audit record to the UI | `AgentResult.audit` is a sanitized copy, the full record stays server-side | The full record holds view SQL, floor-check internals and every row the model saw |
| Report test results from summaries | Check every exit code and stderr | This caught a crashing test suite and a regression the summaries hid (below) |
| Accept gpt-5.5 as the only model that passes | Investigate why gpt-5.4 fails and fix the cause | Same quality at 40% of the cost if it holds |

## Where the models were wrong

**Claude Code, caught by tests, spikes, review agents, or me**

- Its first authorizer keyed on table names, so it blocked reads of its own views. Then a `count(*)` over compliance's unfiltered view was refused, and so was a `count(*)` over any CTE. Each came out of spikes before shipping.
- It used `rowid` on a view, which doesn't exist there.
- It proposed allowing plain filter subqueries for fair_lending. That would have been a leak: `count(*) ... WHERE EXISTS (one person's income > X)` returns 12 or 0. It caught this itself before writing the code.
- Its own prompt notes steered the models wrong three times:
  - "keep the answer short, the table shows the rows" made gpt-5.5 drop numbers and fail t3
  - "any other status word, ask which statuses count" made gpt-5.4 ask on u2 instead of declining
  - "a word that matches a column means that column" made gpt-5.4 answer "average credit score" with `risk_score`
- It committed a test file that crashed on start (a local variable shadowing the `audit` module). It reported it passing because stderr was being thrown away. My exit-code check found it.
- Its secrets scan in zsh passed an unsplit file list to grep, so grep read zero files and "none found" meant nothing. It reran the scan correctly and counted the files read.
- It wrote an eval case (L18) that relied on conversation context the harness doesn't carry, and an in-flight test with a race where the switch could beat the request.
- Its frontend crashed on the first chart on the dev server (Vite re-optimizing `vega-embed` loaded a second React). A review agent found it.

**gpt-5.5, the agent model, in the baseline**

- With the role as a tool argument it claimed `compliance` or `admin` whenever it was refused (c8, L14, L17), and once got race counts that way.
- It answered "0 transactions yesterday" against a fixture that ends in April, added EUR to USD in one total, counted only lowercase `open` alerts, and refused in prose without calling `decline` (L7, L15, L17).

**gpt-5.4 and smaller models, in the benchmark**

- gpt-5.4 asked for a date range on a question with none and never looked at the `transactions` columns, so when it did answer c4 it summed every USD transaction instead of only card ones.
- gpt-5.4-mini and nano refused or asked instead of calling `decline` on leak cases. They never saw restricted data, the server boundary held, but the gate counts the missing decline.
