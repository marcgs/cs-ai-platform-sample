# Backlog

Ideas for later, grouped by theme, with stable IDs. It's not a to-do list: an item is worked on only when the user decides to.

An item belongs here if it does at least one of two things:

- closes a gap between the sample and the [specification](specification.md): its platform capabilities (§5), the governed learning loop (§6) or its requirements (§7);
- tries an Azure technology a real project is likely to use, in the place the platform would use it.

Limitations of Foundry and its tools go in [Foundry findings](foundry-findings.md), not here.

## How to use it

- **Add an item** to the theme it fits, with the next free ID, one sentence of why, and the technology it explores, if any. IDs are never reused or renumbered.
- **Notes** record only verified facts and constraints. Check preview features again when an item is taken.
- **Size** is a rough first guess: **S** up to a day, **M** a few days, **L** a week or more.
- **Remove an item when it's done**; its result goes into the docs it changes.

## Themes

| Theme | What it shows |
|---|---|
| [Q. Evaluation](#q-evaluation) | Scores that tell a better agent from a worse one |
| [L. Learning loop](#l-learning-loop) | Expert feedback becomes approved, replayed improvements (spec §6) |
| [K. Knowledge and data](#k-knowledge-and-data) | Diagnostic knowledge and telemetry beyond the seed data |
| [R. Agent runtimes and channels](#r-agent-runtimes-and-channels) | Other ways to run the agent and reach engineers |
| [S. Security and operations](#s-security-and-operations) | Entra everywhere, central control, and knowing when it breaks |

## Q. Evaluation

Foundry evaluation and its measured quality gate are implemented ([ADR 0011](adr/0011-foundry-evaluation-and-measured-gate.md), [first baseline](../evals/rca/README.md#first-measurement)). These extend them.

| ID | Item | Why | Explores | Size |
|---|---|---|---|---|
| Q5 | **Cost and latency per diagnosis** | Time to diagnosis is the main outcome, and cost decides the model. | Foundry tracing | S |
| Q6 | **Ask instead of guess** | Given a symptom without a machine, the agent picks one and diagnoses it; the report can't ask a question. In one evaluation run, SC-033 used 214k reported tokens doing so, against 7.5k in the run before. | | S |
| Q18 | **Judges checked against expert labels** | A model judge should only gate once its agreement with experts is measured on the same cases. | Foundry evaluators | S |
| Q19 | **Grow thin cohorts** | Four injection cases and twelve missing-machine cases are too few to act on; more cases beat more metrics. | | M |
| Q28 | **Continuous evaluation of live traffic** | Judges on a sample of real runs show drift that a fixed case set misses. | Foundry continuous evaluation | S |
| Q29 | **Metrics that skip cases they don't apply to** | Code evaluators must return a score, so `decisive_evidence_recall` and `injection_resisted` score 1.0 on cases they don't apply to, and the portal's pass counts include those cases. An endpoint evaluator can return `skipped`, but needs a hosted endpoint and a project connection. | Foundry endpoint evaluators | M |

Notes:

- **Q5:** report cost and latency per diagnosis; don't gate on them.
- **Q6:** the missing-machine cases are where the agent does worst: it guesses a machine instead of asking.
- **Q19:** grow where the case count is smallest first: injection, missing machine, then the other challenge categories. Generate them from the seed scenarios, like the existing cases.

## L. Learning loop

Capture and feedback exist. The rest of the specification's loop (§6) comes after evaluation, in this order, and a person merging a pull request is the approval:

1. **Analysis** groups episodes and feedback into patterns and says how strong each signal is.
2. **Cases first.** Patterns where reviewers agree become new test cases, in a pull request.
3. **Then proposals.** A learner turns one pattern into a change to the skill, in a pull request. The platform replays it against the cases and posts the scores.
4. **After release**, the platform checks whether the pattern shrank.

| ID | Item | Why | Explores | Size |
|---|---|---|---|---|
| L3 | **Failure analysis over episodes** | At scale, feedback has to be cleaned, classified and grouped into patterns before anything learns from it; most patterns aren't prompt problems. | Foundry models for classification | M |
| L9 | **Feedback becomes test cases, as a pull request** | The first thing the loop should produce is a better measure, not a changed agent. | | M |
| L4 | **Proposals are replayed and merged** | No change to agent behavior without a passing replay and a person's approval. | Foundry evaluation | M |
| L5 | **A learner drafts proposals** | Turns one pattern into a candidate change to the skill. | Coding agents, Foundry agent optimizer | M |
| L10 | **Release an approved change** | A merged proposal has to become the deployed agent version, and be easy to roll back. | Foundry agent versions | S |
| L11 | **Check the change worked** | Without it nobody knows whether a merged change fixed its pattern, and the loop never closes. | | S |
| L6 | **The loop on a schedule** | Until then a person starts each turn of the loop by hand. | Cosmos DB change feed, Container Apps jobs | M |
| L7 | **Confirmed diagnoses become knowledge** | Every confirmed diagnosis is a new historical case; today the index holds only seed data. | AI Search | S |

Notes:

- **L3, L9:** a first version of both existed and is in the `before-cleanup` tag. What it showed: classifying feedback with a model gives pure but too fine-grained clusters (several clusters per real pattern); admitting a case needs reviewer consensus, a successful replay and no duplicate, not a cluster; and reviewers can agree on a wrong cause, so a case needs a check against the seed scenario for the same input.
- **L5:** checked 2026-10-29. The Foundry agent optimizer improves a hosted agent's instructions, skills, function-tool descriptions and model choice; our tools are MCP, so tool optimization doesn't apply. It scores with an evaluation model on pass/fail criteria and takes a held-out validation dataset. Start with a coding agent writing one diff per pattern and editing only the skill directory, and compare the optimizer with it on the same pattern.
- **L4, first targets:** two behavior gaps seen in earlier measurements. The agent sometimes skips `get_telemetry_window` and calls the unchecked data unavailable, and it often doesn't cite historical cases although its diagnosis is correct.
- **L10:** episodes record the skill version, so every later episode shows which version produced it. Rollback is redeploying the previous version.

## K. Knowledge and data

| ID | Item | Why | Explores | Size |
|---|---|---|---|---|
| K1 | **A knowledge base over historical cases** | A knowledge base plans its own queries and returns cited results, and could serve future document sources too. | Foundry IQ | M |
| K2 | **Manuals and service bulletins as knowledge** | Most diagnostic knowledge lives in documents; the index holds only structured cases. | Content Understanding | L |
| K3 | **Telemetry in a time-series store** | Real telemetry needs a store the tools can query at scale. | Fabric Real-Time Intelligence or Azure Data Explorer | L |
| K4 | **Replayable data for cases from feedback** | A case from an episode only replays truthfully if the tools return what they returned then; the static seed hides this. | | M |

Notes:

- **K2:** needs synthetic documents (manuals, bulletins) consistent with the catalog, with references an evaluator can check.

## R. Agent runtimes and channels

| ID | Item | Why | Explores | Size |
|---|---|---|---|---|
| R1 | **The RCA skill on a managed harness** | Shows what a managed agent loop gives and costs, with the same tools, cases and episodes around it. | Copilot harness | M |
| R2 | **A triage agent calling RCA** | The hosted agent already exposes an A2A endpoint; a triage agent can route to it without glue code. | A2A | M |
| R3 | **Engineers ask from Teams** | Field engineers ask where they already work. | Teams, Microsoft 365 Copilot | M |

Notes:

- **R1:** checked 2026-10-29. The harness rejects `text.format`, so there's no strict `RcaReport`. Every request needs a `conversation`. The agent identity needs the Foundry User role on the project to call a toolbox, assigned after creation. Shell, web, file and subagent tools are on by default. A prompt agent runs none of our code, so episodes must be built outside the agent (from the response and trace).

## S. Security and operations

| ID | Item | Why | Explores | Size |
|---|---|---|---|---|
| S1 | **Entra for the MCP server and platform API** | The last two keys: the MCP function key held by Foundry and the platform API key `csai` fetches. | Functions built-in auth, app registrations | M |
| S2 | **Prompt-injection guardrails** | A logbook entry or tool result can carry instructions; protect at the platform, not only in the prompt. | Foundry guardrails, AI red-teaming agent | M |
| S3 | **AI gateway** | Quotas per agent, logging and failover for models and tools. | API Management | L |
| S4 | **Fleet view and kill switch** | Someone has to see every agent, its cost and errors, and be able to stop one fast. | Foundry Control Plane, Entra Agent ID | M |
| S5 | **Canary diagnosis and alerts** | Failed runs, store outages and rate limiting should page someone. | Foundry monitoring, Azure Monitor alerts | S |
| S6 | **SDK dependency compatibility** | A fresh dependency resolution picks Agent Framework core versions that break the real MCP session; the workspace should declare a range that works. | Agent Framework, MCP | S |
| S7 | **Reproducible offline packaging test** | A freshly recreated environment lacks `hatchling`, so the skill-packaging test fails until it's installed separately. | uv, Hatchling | S |
| S14 | **Verify provision-hook dispatch** | A provision succeeded without running the search-seeding hook; running it by hand worked. | azd hooks | S |
| S16 | **Search tool moderation fails** | The content-safety guardrail isn't running on knowledge searches ([findings](foundry-findings.md#content-safety-moderation-fails-on-every-knowledge-search)). | Foundry guardrails, AI Search tool | S |
| S17 | **Fix the hosted stream's tool calls and usage** | The hosting adapter duplicates tool-call arguments and over-reports usage in the hosted agent's output. A tested workaround is in the closed [#43](https://github.com/marcgs/cs-ai-platform-sample/pull/43); revive it only if something needs those fields. | Agent Framework hosting | S |

Notes:

- **S2:** test with the injection test cases, starting in annotate mode.
- **S6:** `agent-framework-core` 1.23.0 and 1.24.0 with `mcp` 1.30.0 fail `test_real_mcp_session_propagates_episode_context_in_metadata` (`ClientSession.protocol_version` is missing); 1.22.0 passes. Until fixed, sync with `uv sync --all-packages --upgrade-package 'agent-framework-core==1.22.0'`.

## Later

Kept in view, not planned. Each would get a proper item when it becomes relevant.

- Full private networking for Foundry, the registry, AI Search and Application Insights.
- Environments (dev, test, production), promotion and active CI/CD.
- Model comparison across providers, and the model router.
- Conversations (multi-turn) and managed agent memory.
- Long-running diagnoses with a human in the loop, and action tools with approvals.
- Multi-agent workflows.
- Voice for engineers at the machine.
- Edge and on-premises inference (Foundry Local).
- A third agent framework.
