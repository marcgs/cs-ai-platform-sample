# Architecture (iteration 1)

The sample is a minimal CS AI platform with one agent on it. The platform provides the cross-cutting parts once (model access, tools, knowledge, episodes, telemetry, evaluation, deployment); the RCA agent is a spec, instructions, an output schema and an eval suite.

## Components

```mermaid
flowchart LR
    subgraph dev["Developer / SME machine"]
        csai["csai CLI<br/>diagnose · eval · episodes · feedback"]
        local["rca-local / csai --target local<br/>(agent in-process)"]
    end

    subgraph foundry["Microsoft Foundry (account + project, public, Entra only)"]
        model["Model deployments<br/>gpt-5.4-mini · text-embedding-3-large<br/>(DataZoneStandard, EU)"]
        toolbox["Toolbox 'diagnostics'<br/>one MCP endpoint"]
        conns["Connections<br/>diagnostics-mcp (key held by Foundry)<br/>diagnostics-search (Entra)<br/>registry · App Insights"]
        agent["Hosted agent rca-agent<br/>Agent Framework + cs-platform<br/>own agent identity"]
    end

    subgraph vnet["Virtual network"]
        agentsnet["snet-agents<br/>(agent network injection)"]
        funcsnet["snet-functions<br/>(Flex VNet integration)"]
        pes["snet-private-endpoints"]
    end

    mcp["Function app: diagnostics MCP<br/>5 read-only tools"]
    api["Function app: platform API<br/>episodes · feedback"]
    search["AI Search<br/>diagnostics-cases<br/>(hybrid + semantic + vectors)"]
    cosmos[("Cosmos DB<br/>episodes<br/>private")]
    storage[("Functions storage<br/>private")]
    acr["Container registry<br/>(remote builds)"]
    appi["Application Insights<br/>Log Analytics"]

    csai -- "Responses API (Entra)" --> agent
    csai -- "function key via Azure RBAC" --> api
    local --> model
    local --> toolbox
    agent --> model
    agent -- MCP --> toolbox
    toolbox -- "x-functions-key" --> mcp
    toolbox -- Entra --> search
    search -- "query vectorizer" --> model
    agent -. "runs in" .-> agentsnet
    agentsnet --> pes
    mcp -. "runs in" .-> funcsnet
    api -. "runs in" .-> funcsnet
    funcsnet --> pes
    pes --> cosmos
    pes --> storage
    agent -- "episode" --> cosmos
    api --> cosmos
    acr -- image --> agent
    agent -- OTel --> appi
    mcp --> appi
    api --> appi
```

## Capabilities and where they live

| Capability (spec §5) | Implementation |
|---|---|
| **C1** Agent harness | `packages/cs-platform`: `AgentSpec`, `build_agent()`, settings, telemetry. An agent is declared by `agent.spec.yaml` + `instructions.md` + a Pydantic output schema. |
| **C2** Model access | Foundry model deployments (parameters in `infra/main.bicep`); agents read the deployment name from configuration only. |
| **C3** Tool layer | `services/diagnostics-mcp` (MCP server on Azure Functions) behind the Foundry toolbox `diagnostics`; the function key lives only in a Foundry connection. |
| **C4** Knowledge grounding | AI Search index `diagnostics-cases` (historical cases), keyword + semantic + vector search with a Foundry vectorizer, exposed through the same toolbox. Seeded by `scripts/setup_platform.py seed-search`. |
| **C5** Episode store | `cs_platform.capture` middleware records every run (input, tool calls with arguments, results and durations, structured output, tokens, trace ID) in Cosmos DB; feedback is attached through the platform API. |
| **C6** Observability | OpenTelemetry via the Microsoft OpenTelemetry distro to Application Insights; Foundry's trace views read from the connected workspace. |
| **C7** Evaluation | `cs_platform.evals` harness + `evals/rca` suite; `csai eval` gate (exit 1 below thresholds), local or against the hosted agent. |
| **C8** Identity and security | Entra everywhere, `disableLocalAuth` on Foundry, Cosmos DB and Search; no shared keys on storage; data stores private (ADR 0003). The one secret, the MCP function key, never leaves Azure. |
| **C9** Delivery path | Bicep + azd (`azd up` from an empty subscription), pre-commit gates, documented pipeline (`docs/ci-cd.md`). |

## A diagnosis, end to end

1. `csai diagnose "M-0001: ..."` sends the incident to the hosted agent's Responses endpoint with the user's Entra token.
2. Foundry starts (or reuses) a session of the `rca-agent` container in the agent subnet.
3. The harness opens an episode, then Agent Framework runs the model loop: the model calls `get_machine_context`, `get_error_events`, `lookup_error_code`, `get_telemetry_window`, `get_logbook` (and optionally `azure_ai_search`) through the toolbox; the capture middleware records every call.
4. The model returns an `RcaReport` (strict structured output): ranked hypotheses, each with cited refs.
5. The harness completes the episode and writes it to Cosmos DB over its private endpoint, as the agent's identity.
6. `csai` prints the report and derives the episode's point-read key from the host-issued Responses ID. It uses bounded polling through the platform API and verifies the stored `hosted_response_id`; it never selects an episode by incident text, time or session. An expert attaches a verdict with `csai feedback`.

## Identities and access

| Identity | Gets | Defined in |
|---|---|---|
| Developer (azd principal) | Foundry User, AcrPush; Cosmos DB data contributor; Search service and index data contributor | `developer-access.bicep`, `cosmos.bicep`, `search.bicep` |
| Foundry project (system-assigned) | AcrPull; Log Analytics Reader; Foundry User; Search service and index data contributor | `foundry.bicep`, `search.bicep` |
| Foundry account (system-assigned) | Search service and index data contributor (AI Search tool) | `search.bicep` |
| Search service (system-assigned) | Cognitive Services OpenAI User on the Foundry account (query vectorizer) | `search.bicep` |
| Hosted agent (agent identity) | Project endpoint by default; Cosmos DB data contributor | `scripts/setup_platform.py grant-agent` (exists only after deploy) |
| MCP app (user-assigned) | Storage blob/queue/table data roles; Monitoring Metrics Publisher | `function-app.bicep` |
| Platform API (user-assigned) | As the MCP app, plus Cosmos DB data contributor | `function-app.bicep`, `main.bicep` |

## Network

See ADR 0003. Storage and Cosmos DB have public access disabled (also enforced by policy in the original subscription) and private endpoints with private DNS zones. The function apps use VNet integration; the hosted agent runs in a delegated subnet through Foundry agent network injection, which is set when the Foundry account is created. Foundry, the registry and AI Search stay public with Entra-only access so developers can deploy from their machines.

## Deployment

`azd up` runs, in order:

1. Bicep (`infra/main.bicep`): network, monitoring, Foundry, registry, Cosmos DB, AI Search, connections, function apps, roles.
2. `postprovision`: create and seed the search index.
3. Services: package the function apps (`scripts/package_function.sh`, locked Linux wheels) and deploy them; `postdeploy` of the MCP app stores its key in a Foundry connection and publishes the toolbox; export the locked requirements and build the agent image in ACR, create the hosted agent version; `postdeploy` grants the agent identity its Cosmos DB role.
