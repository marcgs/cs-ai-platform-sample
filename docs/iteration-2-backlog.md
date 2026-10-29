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

## Platform scope deferred by the specification

- **Outer learning loop:** periodic review of episodes and feedback, proposals for instruction/knowledge changes, SME approval workflow (e.g. Logic Apps), replay of approved changes against past cases with the eval gate.
- **AI gateway:** API Management in front of models and tools (quotas per agent, logging, failover).
- **Full private networking:** private endpoints for Foundry, the registry, AI Search and Application Insights (Azure Monitor Private Link Scope); deployments and evals from self-hosted runners in the network.
- **Unstructured knowledge ingestion:** Content Understanding for PDFs and emails into the knowledge index.
- **Telemetry analytics:** a real-time store (Fabric / Azure Data Explorer) for machine telemetry; Cosmos DB mirroring for episode analytics and dashboards.
- **Channels:** Teams / Copilot Studio for field engineers; a small read-only episode viewer on the platform API.
- **More agents and orchestration:** action planning and repair agents, multi-agent workflows; model comparison across providers.
- **Governance:** Purview, Defender for AI, guardrail policies on hosted agents.
- **CI/CD:** activate the pipeline sketched in `docs/ci-cd.md` (committed public-PyPI lock files, OIDC, eval gate on PRs).
