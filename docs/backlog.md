# Backlog

Open work for the platform, grouped by theme, with stable IDs (`Q3`) that iteration plans refer to.

An item belongs here if it does at least one of two things:

- closes a gap between the sample and the [specification](specification.md): its platform capabilities (§5), the governed learning loop (§6) or its requirements (§7);
- tries an Azure technology the project is likely to use, in the place the platform would use it.

Everything else goes under [Later](#later) as one line, or is left out. Items removed in the October 2026 rework are in git history (commit `f19dbc8`).

## How to use it

- **Add an item** to the theme it fits, with the next free ID, one sentence of why, and the technology it explores, if any. IDs are never reused or renumbered.
- **Notes** record only verified facts and constraints. Design belongs in the iteration plan, written when the item is taken; check preview features again at that point.
- **Size** is a rough first guess: **S** up to a day, **M** a few days, **L** a week or more.
- **Target** is empty until an iteration takes the item; then it names the iteration (`it3`). Remove completed items, and keep their evidence and pull request links in the iteration record (`docs/iteration-N/`).
- An iteration's scope and order live in its plan (`docs/plan-iteration-N.md`).

## Themes

| Theme | What it shows |
|---|---|
| [Q. Evaluation you can trust](#q-evaluation-you-can-trust) | Scores that tell a better agent from a worse one |
| [L. Governed learning loop](#l-governed-learning-loop) | Expert feedback becomes approved, replayed improvements (spec §6) |
| [K. Knowledge and data](#k-knowledge-and-data) | Diagnostic knowledge and telemetry beyond the seed data |
| [R. Agent runtimes and channels](#r-agent-runtimes-and-channels) | Other ways to run the agent and reach engineers |
| [S. Security and operations](#s-security-and-operations) | Entra everywhere, central control, and knowing when it breaks |

## Q. Evaluation you can trust

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| Q1 | **Tool-selection reliability** | The gate is red: the agent skips `get_telemetry_window` in up to 10 of 18 cases (`tool_coverage` 0.89 against 0.90) and calls the unchecked data unavailable. | | M | it3 |
| Q2 | **Eval health** | Nobody knows how much scores vary between runs, or whether a failure was the model or the plumbing. | | M | done it3 ([#13](https://github.com/marcgs/cs-ai-platform-sample/pull/13)) |
| Q3 | **Harder cases with ground truth** | All 18 cases pass at baseline, so the suite can't show improvement, and a root-cause label can't tell a sound diagnosis from a lucky guess. | | M | it3 |
| Q4 | **Gate on outcomes, with model judges** | `tool_coverage` rewards a ritual, and the specification asks for model-based evaluators. | `azure-ai-evaluation` | S | |
| Q5 | **Cost and latency per diagnosis** | Time to diagnosis is the main outcome, and cost decides the model. | Foundry tracing | S | |
| Q6 | **Ask instead of guess** | Given a symptom without a machine, the agent picks one and diagnoses it; the report can't ask a question. | | S | |
| Q7 | **Knowledge-citation reliability** | The pinned iteration-3 baseline cites historical knowledge in only 24 of 54 runs, below the unchanged 0.70 gate despite correct diagnoses; investigate retrieval versus citation failures without forcing irrelevant citations. | | M | |
| Q8 | **Durable in-progress eval capture** | A fatal interruption can discard completed results and episodes before the CLI's final export; checkpoint actual records without turning cancellation or recovery into quality-seeking resampling. | | M | |

Notes:

- **Q1:** found in the [PR #9](https://github.com/marcgs/cs-ai-platform-sample/pull/9) review; the failed run was accepted as recorded, not as a pass. Earlier suites skipped the tool in 7–8 cases. The numbered instruction alone is insufficient. Keep the threshold; don't rerun to get a pass.
- **Q2:** repeats with confidence intervals, plumbing failures apart from wrong answers, per-case transcripts, a saturation warning, and train and held-out cases split by machine (the keep/revert rule that L4 relies on).
- **Q3:** decisive evidence, acceptable alternatives and ruled-out modes per scenario; categories such as overlapping, no fault found, out of catalog, missing machine, injection and noisy data. Keep the 18 existing cases byte-identical so the baseline stays comparable.
- **Q3, preparation:** the 50-case generator, truthful tools and causal evaluators are offline implementation-ready. The original18 gate and frozen legacy outputs are protected. Deployment-dependent headroom and ablation acceptance remain outstanding; see [Q3 evidence](iteration-3/q3.md).
- **Q4:** a change to which metrics gate needs the user's approval, and not as Q1's fix.
- **Q7:** the [retained Q2 baseline](iteration-3/q2.md) ran the unchanged `fae76ff` agent and dataset, 18 cases with three repeats at concurrency one. `used_knowledge` was 0.444 (95% CI approximately 0.28–0.61), while `hit_at_1` was 1.00 and search was called in 0.67 of runs. The run failed and was retained; no threshold was lowered and no rerun was used to seek a pass.
- **Q8:** the first isolated L1 measurement was cancelled during MCP tool discovery after 25 completed case-runs. Only rounded console observations survived; no complete result or episode export was written. Private recovery drivers journal actual records immediately, but the public CLI still exports after the suite. Preserve genuine cancellation and failed attempts; do not reconstruct missing episodes from scores.

## L. Governed learning loop

Capture and feedback exist. This theme adds the rest of the specification's loop: find recurring failures, propose a change, replay it and let an expert approve it. Only the propose step uses a learner; the rest is deterministic.

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| L1 | **The RCA procedure as a skill** | A versioned skill is the unit the loop changes and the optimizer works on. | Agent Framework skills, Foundry skills | S | it3 |
| L2 | **Synthetic expert feedback** | The loop needs feedback with realistic patterns and noise, including wrong reviews that must not push a change through. | | S | done it3 ([#14](https://github.com/marcgs/cs-ai-platform-sample/pull/14)) |
| L3 | **Failure analysis over episodes** | At scale, feedback has to be cleaned, classified and ranked into clusters before anything learns from it; most clusters aren't prompt problems. | Cosmos DB mirroring to Fabric, Foundry models for classification | M | it3 |
| L4 | **Proposals, replay and approval** | No change to agent behavior without a passing replay and an expert's approval. | | M | |
| L5 | **A learner drafts proposals** | Turns one diagnosed cluster into a candidate skill or model change. | Foundry agent optimizer | M | |
| L6 | **Scheduled review and approval flow** | The periodic review and the expert's approval, outside a terminal. | Cosmos DB change feed, Logic Apps | M | |
| L7 | **Confirmed diagnoses become knowledge** | Every confirmed diagnosis is a new historical case; today the index holds only seed data. | AI Search | S | |

Notes:

- **L3:** routes each cluster to its owner: behavior to L5, knowledge to L7, tools or data to this backlog, and reproducing cases to the eval suite.
- **L4:** the platform turns feedback into eval cases (the expert's verdict is the ground truth), replays the proposal on them and on the train and held-out cases (Q2), and an expert approves. The learner never edits evaluators, thresholds or cases, and never sees held-out transcripts.
- **L5:** checked 2026-10-29. The optimizer improves a hosted agent's instructions, skills, function-calling tool descriptions and model choice. The agent loads its configuration through the optimizer package (`load_config()`). Our tools are MCP, so tool optimization doesn't apply. It scores with an eval model on binary criteria; `eval.yaml` takes a held-out `validation_dataset`, which should come from Q2's test split. Verify first that it runs in a network-injected project (Foundry cloud evaluations don't; see Later) and whether it can score with our evaluators. Fallback learner: Claude Code, editing only the skill directory.

## K. Knowledge and data

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| K1 | **A knowledge base over historical cases** | A knowledge base plans its own queries and returns cited results, and could serve future document sources too. | Foundry IQ | M | |
| K2 | **Manuals and service bulletins as knowledge** | Most diagnostic knowledge lives in documents; the index holds only structured cases. | Content Understanding | L | |
| K3 | **Telemetry in a time-series store** | Real telemetry needs a store the tools can query at scale. | Fabric Real-Time Intelligence or Azure Data Explorer | L | |

Notes:

- **K2:** needs synthetic documents (manuals, bulletins) consistent with the catalog, with refs the evaluators can check.

## R. Agent runtimes and channels

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| R1 | **The RCA skill on a managed harness** | Shows what a managed agent loop gives and costs, with the same tools, suite and episodes around it. | Copilot harness | M | |
| R2 | **A triage agent calling RCA** | The hosted agent already exposes an A2A endpoint; a triage agent can route to it without glue code. | A2A | M | |
| R3 | **Engineers ask from Teams** | Field engineers ask where they already work. | Teams, Microsoft 365 Copilot | M | |

Notes:

- **R1:** checked 2026-10-29. The harness rejects `text.format`, so there's no strict `RcaReport`. Every request needs a `conversation`. The agent identity needs the Foundry User role on the project to call a toolbox, assigned after creation. Shell, web, file and subagent tools are on by default. Sweden Central is supported. A prompt agent runs none of our code, so episodes must be built outside the agent (from the response and trace).

## S. Security and operations

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| S1 | **Entra for the MCP server and platform API** | The last two keys: the MCP function key held by Foundry and the platform API key `csai` fetches. | Functions built-in auth, app registrations | M | |
| S2 | **Prompt-injection guardrails** | A logbook entry or tool result can carry instructions; protect at the platform, not only in the prompt. | Foundry guardrails, AI red-teaming agent | M | |
| S3 | **AI gateway** | Quotas per agent, logging and failover for models and tools. | API Management | L | |
| S4 | **Fleet view and kill switch** | Someone has to see every agent, its cost and errors, and be able to stop one fast. | Foundry Control Plane, Entra Agent ID | M | |
| S5 | **Canary diagnosis and alerts** | Failed runs, store outages and rate limiting should page someone. | Foundry monitoring, Azure Monitor alerts | S | |
| S6 | **SDK dependency compatibility** | A fresh dependency resolution can break the real MCP session even when the baseline local resolution passes; verify compatible SDK ranges without committing a lock file. | Agent Framework, MCP | S | |

Notes:

- **S2:** test with Q3's injection cases, starting in annotate mode.
- **S6:** found during iteration-3 validation: `agent-framework-core` 1.23.0 with `mcp` 1.30.0 fails both parameterizations of `test_real_mcp_session_propagates_episode_context_in_metadata` because `ClientSession.protocol_version` is absent. Framework core 1.22.0 with MCP 1.30.0 passes. No compatibility constraint was changed as part of Q2.
- **S6, live observation:** the isolated L1 attempt also encountered cancellation inside `FoundryToolbox.connect` / `session.list_tools` with core 1.22.0 and MCP 1.30.0. Its origin is unproven; the traceback does not distinguish an SDK lifecycle defect from a transient fault.

## Later

Kept in view, not planned. Each would get a proper item when it becomes relevant.

- Full private networking for Foundry, the registry, AI Search and Application Insights.
- Foundry-published and continuous evaluations (need capability hosts, which a network-injected project gets only at creation).
- Model comparison across providers, and the model router.
- Conversations (multi-turn) and managed agent memory.
- Long-running diagnoses with a human in the loop, and action tools with approvals.
- Multi-agent workflows.
- Voice for engineers at the machine.
- Edge and on-premises inference (Foundry Local).
- Environments, promotion and active CI/CD.
- A third agent framework.
