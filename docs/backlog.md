# Backlog

Every idea for the platform in one place: findings from running it, scope the [specification](specification.md) defers, and new directions. Items are grouped by theme and have a stable ID (`B3`), so iteration plans can refer to them.

## How to use it

- **Add an idea** to the theme it fits, with the next free ID. IDs are never reused or renumbered.
- **Size** is a rough first guess: **S** up to a day, **M** a few days, **L** a week or more.
- **Target** is empty until an iteration takes the item; then it names the iteration (`it2`). When an item is done, write `done it2` and link the pull request in the notes.
- An iteration's scope and order live in its plan (`docs/plan-iteration-N.md`), which lists the IDs it takes.

## Themes

| Theme | What it would show |
|---|---|
| [A. Trustworthy results](#a-trustworthy-results) | That eval scores and traces can be relied on, so changes can be compared |
| [B. Controlled learning](#b-controlled-learning) | The specification's learning loop: agents improve from expert feedback, and nothing ships without approval and replay |
| [C. Any agent harness](#c-any-agent-harness) | That tools, evals, episodes and identity are platform services around any agent loop |
| [D. Better diagnoses](#d-better-diagnoses) | Product quality for field engineers: conversations, richer knowledge and data |
| [E. Several agents](#e-several-agents) | Agents composed into a workflow, through Foundry |
| [F. Where people use it](#f-where-people-use-it) | The human side: experts reviewing, engineers asking where they already work |
| [G. Measuring quality](#g-measuring-quality) | Quality, cost and latency measured well enough to choose models and changes |
| [H. Security and governance](#h-security-and-governance) | Entra everywhere, central control of model and tool use |
| [I. Operations](#i-operations) | Running the platform: metrics, alerts, retention, CI |

## A. Trustworthy results

Most of these came from running iteration 1. Without them, eval scores move for reasons unrelated to the change being tested.

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| A1 | **Rate-limit handling** | About 1 in 6 hosted runs fail on the first attempt when parallel runs exceed the 50k TPM deployment; the hosted agent returns an empty failed response instead of retrying. | Retry with backoff on 429 in the platform's chat client; raise `chatModel.capacity` (pay-per-token, quota permitting); record the failure in the episode. A gateway (H3) is the long-term answer. | S | |
| A2 | **Knowledge search is almost never used** | `used_knowledge` is 0.00–0.06 across eval runs, although the toolbox's `azure_ai_search` tool works and returns relevant historical cases. | Give the search tool a specific description (toolbox tool metadata), require a historical-case search in the instructions, then gate `used_knowledge` once it's stable. | S | |
| A3 | **Trace gaps** | A current hosted run's trace has the agent, model turns and toolbox calls, and its `operation_Id` matches the episode's trace ID (checked 2026-10-29). But runs from 2026-10-28 left no telemetry at all, and local `rca-local` episodes show `trace n/a`. | Find why the earlier runs are missing; check that MCP server spans join the agent's trace; fix local trace IDs; decide on sampling. | S | |
| A4 | **Episode–response correlation** | `csai diagnose` finds a hosted run's episode by input and time. | Record the Responses `response_id` or session ID in the episode, or return the episode ID in response metadata. | S | |
| A5 | **Deploy the review fixes** | The deployed agent and function apps predate the PR #1 review fixes: full tool results within an episode size budget, nested `.env` files excluded from the image. | `azd deploy`, then a hosted diagnosis and `csai episodes show` to confirm. | S | |
| A6 | **Toolbox call latency** | 4–18 s per tool call through the toolbox versus about 50 ms against the MCP server directly; a diagnosis takes about a minute. | Measure with traces (toolbox proxy, Flex cold starts, MCP session setup per call); consider always-ready instances for the MCP app. | M | |

## B. Controlled learning

The idea: make **skills** the unit the platform versions, evaluates and improves, and let a self-improving harness propose changes that only an expert and the eval gate can release. [Hermes Agent](https://hermes-agent.nousresearch.com/docs) (open source) has a built-in learning loop that writes and refines its own skills, in the open agentskills.io format.

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| B1 | **The RCA procedure as a skill** | The agent's behavior is buried in `instructions.md`. A skill is a versioned, reviewable artifact, and the unit the learning loop changes. It's also what C1 runs on another harness. | Move the investigation procedure and answer rules to `skills/rca-investigation/` (`SKILL.md`, plus a script only if one earns its place). `rca-agent` loads it with no change in behavior; the eval baseline proves it. Check how Agent Framework loads skills. | S | |
| B2 | **Episodes and feedback as MCP tools** | Gives a learner agent governed, read-only access to what experts said. | Read-only MCP tools on the platform API (list episodes by verdict, get episode), behind the same identity and network rules. | S | |
| B3 | **Proposals, replay and approval** | The specification's controlled loop: no change to agent behavior without expert approval and a passing replay. | A proposal is a skill change plus new eval cases that reproduce the mistakes it fixes. `csai eval` replays it against those cases and the full suite, and must fix them without regressions. An expert approves (`csai proposals approve`, or a pull request review), and `azd deploy` releases it as a new agent version linked to the proposal. | M | |
| B4 | **Hermes as the learner** | Hermes's self-improvement is what the loop needs, but uncontrolled; behind the gate (B3), it only proposes. | A hosted container (bring-your-own-framework path) on Foundry models, using the B2 tools to draft proposals from episodes marked incorrect. Its Foundry guide covers Foundry as a model provider, not as a hosted agent: verify that first. Needs a supply-chain review as a third-party dependency, and an image built in Azure. First target: D1. | M | |
| B5 | **Confirmed cases become knowledge** | Every expert-confirmed diagnosis is a new historical case; today the index only holds seed data. | Turn episodes with a confirmed root cause into `diagnostics-cases` documents, as a proposal an expert approves (B3). | S | |
| B6 | **Scheduled review and an approval flow** | The specification's periodic review of episodes, with approvals outside a terminal. | Run the learner on a schedule; approvals through Logic Apps or the review app (F1). | M | |

## C. Any agent harness

The question: does the platform work for agents it didn't build? The [Copilot harness](https://devblogs.microsoft.com/foundry/microsoft-copilot-harness-in-foundry/) in Foundry (public preview, runtime free until 2026-12-01) is a managed agent loop for prompt agents, with skills, MCP tools, a sandbox and subagents, declared in `azure.yaml` (`harness: microsoft_copilot_preview`).

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| C1 | **The RCA skill on the Copilot harness** | Shows what a managed harness gives (no orchestration code) against what it costs (control, middleware), with the same platform around both. | A prompt agent `rca-harness` with the B1 skill and the `diagnostics` toolbox as its MCP tool, registered in `csai` and gated by the same suite and thresholds. Check first: strict structured output (`RcaReport`), region availability, toolbox endpoints as MCP tools, network-injected projects. | M | |
| C2 | **Episode capture outside the agent** | Capture is middleware inside our own code, and a managed harness has no place for it. | Build episodes from the Responses output (tool calls, final answer) and the trace, in the platform API or `csai`. Keep the in-process capture for code agents, and compare the two records. | M | |
| C3 | **A third framework** | A second code framework shows what onboarding costs when the agent isn't Agent Framework. | LangGraph, Claude Agent SDK, OpenAI Agents SDK or GitHub Copilot SDK as a hosted container, using the same skill, toolbox, store and suite. | M | |

## D. Better diagnoses

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| D1 | **Ask instead of guess** | Given "Overlay is drifting." with no machine, the agent picked M-0001 itself and diagnosed it. The report schema always demands a diagnosis, so the agent can't ask which machine. | Let the report express "need more information" (or validate the input before the run), support a follow-up turn, and add eval cases for missing and ambiguous machine IDs. | S | |
| D2 | **Conversations** | Engineers ask follow-up questions ("why not a vacuum leak?"); the CLI and eval are single-shot. | Multi-turn through the Responses API (previous response or session); episodes linked per conversation; multi-turn eval cases. | M | |
| D3 | **Knowledge from documents** | Manuals, service bulletins and emails hold most diagnostic knowledge; the index has only structured cases. | Content Understanding to extract PDFs and emails into the knowledge index, with refs the evaluators can check. | L | |
| D4 | **Telemetry at scale** | Seed data is small; real telemetry needs a time-series store. | Fabric Real-Time Intelligence or Azure Data Explorer behind the MCP telemetry tool. | L | |
| D5 | **Tool approvals** | Once tools can act (open a ticket, order a part), a human must approve. | Approvals on MCP tools in the toolbox or harness; approval recorded in the episode. Needs an action tool first (E2). | M | |

## E. Several agents

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| E1 | **Triage agent calling RCA over A2A** | The hosted agent already exposes an A2A endpoint (`AGENT_RCA_AGENT_A2A_ENDPOINT` in the azd environment). Agents could call each other through Foundry, without glue code. | A small triage agent that routes an incident to RCA (or asks for missing details) and calls it over A2A; one episode per agent, linked. | M | |
| E2 | **Repair-planning agent** | The specification's next agents: from a confirmed root cause to a repair plan with parts and steps. | Onboard with [`onboarding-an-agent.md`](onboarding-an-agent.md); its first action tool needs D5. | M | |
| E3 | **Multi-agent workflows** | Triage → RCA → planning as one governed workflow. | Agent Framework workflows or Foundry workflows; an eval for the whole chain. | L | |

## F. Where people use it

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| F1 | **Expert review app** | Today feedback is CLI commands; experts need to see the evidence and give a verdict quickly. | A small web app on the platform API: episode list, report with evidence and tool results, feedback form. Needs H2 for user identity. | M | |
| F2 | **Teams or Microsoft 365 Copilot** | Field engineers ask where they already work. | Publish the agent to Teams or Microsoft 365 Copilot, or front it with Copilot Studio. | M | |

## G. Measuring quality

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| G1 | **Harder eval cases** | 18 synthetic cases, all solved at baseline: the suite checks regressions, not headroom. | Ambiguous symptoms, misleading logbook entries, unknown machines, injected instructions, multi-turn follow-ups; per-failure-mode breakdowns. | M | |
| G2 | **Model-graded judges, locally** | The specification asks for model-based evaluators; there are none yet. | Groundedness, task adherence and intent resolution from `azure-ai-evaluation`, run by the harness next to the code evaluators. | S | |
| G3 | **Evaluations published to Foundry** | `csai eval --publish` fails in a network-injected project: cloud evaluations need account- and project-level capability hosts (and evaluation storage). | Capability hosts must be set when the project is created: plan a rebuild, or a separate evaluation project. G2 covers the judges in the meantime. | M | |
| G4 | **Red-teaming** | Prompt injection through tool data and user input is a real risk for a diagnostics agent. | Foundry's AI red-teaming agent against `rca-agent`; findings become eval cases (G1). | M | |
| G5 | **Cost and latency per diagnosis** | "Time to diagnosis" is the specification's main outcome, and cost decides which model to use. | Record tokens, cost and duration per episode and per eval case; report them in `csai eval`. | S | |
| G6 | **Model comparison** | The model is configuration; numbers should drive the choice. | Run the suite across models and providers; compare quality against cost and latency (G5). | M | |

## H. Security and governance

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| H1 | **MCP authentication with Entra** | The MCP server uses a function key (held only by Foundry). | Functions built-in authentication with an app registration (Graph Bicep extension) and a project-managed-identity connection; disable key auth. | M | |
| H2 | **Platform API authentication with Entra** | `csai` fetches the API's function key with the caller's Azure RBAC. | Built-in authentication with an app registration; roles for experts (feedback, approvals) vs. readers. | M | |
| H3 | **AI gateway** | Quotas per agent, logging and failover for models and tools; the proper fix for A1. | API Management in front of model deployments and MCP tools. | L | |
| H4 | **Full private networking** | Foundry, the registry, AI Search and Application Insights are still public (Entra only). | Private endpoints and an Azure Monitor Private Link Scope; deployments and evals from self-hosted runners in the network. | L | |
| H5 | **Governance** | Data classification and threat protection for AI workloads. | Purview, Defender for AI, guardrail policies on hosted agents. | M | |

## I. Operations

| ID | Item | Why | Notes | Size | Target |
|---|---|---|---|---|---|
| I1 | **Platform metrics dashboard** | Show the platform's value: diagnoses per day, accuracy from expert feedback, time and cost per diagnosis, failures. | An Azure Monitor workbook over Application Insights; Cosmos DB mirroring to Fabric for episode analytics. | M | |
| I2 | **Alerts** | Failed runs, store outages and rate limiting should page someone. | Alert rules on failed episodes, "Could not save episode" logs and 429s. | S | |
| I3 | **Episode retention** | Episodes are kept indefinitely. | A retention policy (Cosmos DB TTL) agreed with the data owners; keep feedback-bearing episodes longer. | S | |
| I4 | **CI/CD** | Gates are local only. | Activate the pipeline sketched in [`ci-cd.md`](ci-cd.md): committed public-PyPI lock files, OIDC, eval gate on pull requests. | M | |
