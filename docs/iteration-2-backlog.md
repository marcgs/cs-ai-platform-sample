# Iteration 2 backlog

Findings from building and running iteration 1, then the larger items the specification defers. Roughly in priority order within each section.

## Findings from iteration 1

| Item | Why | Notes |
|---|---|---|
| **Model capacity and rate-limit handling** | About 1 in 6 hosted runs fail on the first attempt when parallel runs exceed the 50k TPM deployment; the hosted agent returns an empty failed response instead of retrying. | Raise `chatModel.capacity` (pay-per-token, quota permitting); add retry with backoff on 429 in the harness's chat client; surface failures as errors in the episode. |
| **Knowledge search is almost never used** | `used_knowledge` is 0.00–0.06 across eval runs, although the toolbox's `azure_ai_search` tool works and returns relevant historical cases. | Give the search tool a specific description (toolbox tool metadata), require a historical-case search in the instructions, then gate `used_knowledge` once it's stable. |
| **Toolbox call latency** | 5–25 s per tool call through the toolbox versus about 50 ms against the MCP server directly. | Measure with traces (toolbox proxy, Flex cold starts, MCP session setup per call); consider always-ready instances for the MCP app. |
| **Foundry-published evaluations** | `csai eval --publish` fails in a network-injected project: cloud evaluations need account- and project-level capability hosts (and evaluation storage). | Capability hosts must be set when the project is created: plan a rebuild, or a separate evaluation project. Alternatively run the built-in judges locally with `azure-ai-evaluation`. |
| **Traces in Application Insights** | Checked on 2026-10-29: a hosted run's trace has the agent, model turns and toolbox calls, the MCP app and platform API report too, and the trace's `operation_Id` matches the episode's trace ID. But runs from 2026-10-28 left no telemetry at all, and local `rca-local` episodes show `trace n/a`. | Find why the earlier runs are missing; check that MCP server spans join the agent's trace; fix local trace IDs; decide on sampling and retention. |
| **MCP authentication with Entra** | The MCP server uses a function key (held only by Foundry). | Functions built-in authentication with an app registration (Graph Bicep extension) and a project-managed-identity connection; disable key auth. |
| **Platform API authentication with Entra** | `csai` fetches the API's function key with the caller's Azure RBAC. | Built-in authentication with an app registration; roles for SMEs (feedback) vs. readers. |
| **Episode–response correlation** | `csai diagnose` finds a hosted run's episode by input and time. | Record the Responses `response_id` / session ID in the episode, or return the episode ID in response metadata. |
| **Incidents without a machine ID** | Given "Overlay is drifting." with no machine, the agent picked M-0001 itself and diagnosed it. The report schema always demands a diagnosis, so the agent can't ask which machine. | Let the report express "need more information" (or validate the input before the run), and add eval cases for missing and ambiguous machine IDs. |
| **Eval suite depth** | 18 synthetic cases, all solved at baseline: the suite checks regressions, not headroom. | Harder cases (ambiguous symptoms, misleading logbook entries, unknown machines, injected instructions), multi-turn follow-ups, per-failure-mode breakdowns. |
| **Deploy the review fixes** | The deployed agent and function apps predate the PR #1 review fixes: full tool results within an episode size budget, nested `.env` files excluded from the image. | `azd deploy`, then a hosted diagnosis and `csai episodes show` to confirm. |

## Proposed focus: skills, harnesses and a controlled learning loop

Two questions iteration 2 has to answer: is the platform independent of the agent harness (tools, evals, episodes and identity as platform services around any agent loop), and how does an agent improve without losing expert control? Two new options help answer both:

- The [Copilot harness](https://devblogs.microsoft.com/foundry/microsoft-copilot-harness-in-foundry/) in Foundry (public preview): a managed agent loop for prompt agents, with skills, MCP tools, a sandbox and subagents, declared in `azure.yaml` (`harness: microsoft_copilot_preview`). Runtime is free until 2026-12-01.
- [Hermes Agent](https://hermes-agent.nousresearch.com/docs) (open source): a harness with a built-in learning loop that writes and refines its own skills, with memory and MCP support, and skills in the open agentskills.io format.

The idea: make **skills** the unit the platform versions, evaluates and improves; run them on more than one harness; and let a self-improving harness propose changes that only an expert and the eval gate can release.

Do the findings above first, at least rate limits, knowledge search, traces and episode correlation. Otherwise eval scores move for reasons unrelated to the change being compared. Then, in order:

| Item | Why | Notes |
|---|---|---|
| **The RCA procedure as a skill** | Today the agent's behavior is buried in `instructions.md`. A skill is a versioned, reviewable artifact, and the unit the learning loop changes. | Move the investigation procedure and answer rules to `skills/rca-investigation/` (`SKILL.md`, plus a script only if one earns its place). `rca-agent` loads it with no change in behavior; the eval baseline proves it. Check how Agent Framework loads skills. |
| **The same skill on the Copilot harness** | Shows what a managed harness gives (no orchestration code) against what it costs (control, middleware), with the same platform around both. | A prompt agent `rca-harness` in `azure.yaml` with the skill and the `diagnostics` toolbox as its MCP tool, registered in `csai` and gated by the same suite and thresholds. Check first: strict structured output (`RcaReport`), region availability, toolbox endpoints as MCP tools, and network-injected projects. |
| **Episode capture outside the agent** | Capture is middleware inside our own code, and a managed harness has no place for it. A platform that accepts agents it didn't build has to capture episodes from outside. | Build episodes from the Responses output (tool calls, final answer) and the trace, for example in the platform API or `csai`. Keep the in-process capture for code agents, and compare the two records. |
| **Episodes and feedback as MCP tools** | Gives a learner agent governed, read-only access to what experts said. | Read-only MCP tools on the platform API (list episodes by verdict, get episode), behind the same identity and network rules. |
| **Proposals, replay and approval** | The specification's controlled learning loop: no change to agent behavior without expert approval and a passing replay. | A proposal is a skill change plus new eval cases that reproduce the mistakes it fixes. `csai eval` replays it against those cases and the full suite, and must fix them without regressions. An expert approves (`csai proposals approve`, or a pull request review), and `azd deploy` releases it as a new agent version linked to the proposal. |
| **Hermes as the learner** | Hermes's self-improvement is what the loop needs, but uncontrolled; behind the gate, it only proposes. | A hosted container (bring-your-own-framework path) on Foundry models, using the episode tools to draft proposals from episodes marked incorrect. Its Foundry guide covers Foundry as a model provider, not as a hosted agent, so verify that first. It also needs a supply-chain review as a third-party dependency, and an image built in Azure. First target: incidents without a machine ID, where the agent guesses a machine instead of asking. |

## Platform scope deferred by the specification

- **Outer learning loop:** periodic review of episodes and feedback, proposals for instruction/knowledge changes, SME approval workflow (e.g. Logic Apps), replay of approved changes against past cases with the eval gate. A first version is proposed above; scheduling and a Logic Apps approval flow stay deferred.
- **AI gateway:** API Management in front of models and tools (quotas per agent, logging, failover).
- **Full private networking:** private endpoints for Foundry, the registry, AI Search and Application Insights (Azure Monitor Private Link Scope); deployments and evals from self-hosted runners in the network.
- **Unstructured knowledge ingestion:** Content Understanding for PDFs and emails into the knowledge index.
- **Telemetry analytics:** a real-time store (Fabric / Azure Data Explorer) for machine telemetry; Cosmos DB mirroring for episode analytics and dashboards.
- **Channels:** Teams / Copilot Studio for field engineers; a small read-only episode viewer on the platform API.
- **More agents and orchestration:** action planning and repair agents, multi-agent workflows; model comparison across providers.
- **Governance:** Purview, Defender for AI, guardrail policies on hosted agents.
- **CI/CD:** activate the pipeline sketched in `docs/ci-cd.md` (committed public-PyPI lock files, OIDC, eval gate on PRs).
