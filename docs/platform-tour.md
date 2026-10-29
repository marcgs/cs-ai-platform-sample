# Platform tour

A guided tour of a deployed environment: what each platform capability is for, and where to find it in Azure and in the code. It complements the [walkthrough](walkthrough.md), which shows how to *use* the sample; run that first, since the tour refers to its steps. Plan about an hour and a half; each part also works on its own. The tour only reads things in Azure.

## Before you start

- An environment deployed with `azd up` (see the [README](../README.md#quickstart)).
- Signed in with `azd auth login` and `az login`, in the same tenant.
- Shell variables for the names used below, read from your azd environment:

```bash
eval "$(azd env get-values | grep -E '^(AZURE_RESOURCE_GROUP|AZURE_AI_ACCOUNT_NAME|AZURE_SEARCH_NAME|AZURE_SEARCH_INDEX_NAME|COSMOS_ACCOUNT_NAME)=')"
RG=$AZURE_RESOURCE_GROUP
APPI=$(az resource list -g $RG --resource-type microsoft.insights/components --query "[0].name" -o tsv)
```

Each stop has the same parts:

- **The idea:** what the capability is for, and the design choice behind it.
- **Look:** where to find it in the Azure portal or the [Foundry portal](https://ai.azure.com).
- **Try:** commands to run.
- **Check yourself:** a question to test what you've learned. The answers are at the end.

Preview features (hosted agents, toolboxes) move around in the portals. If a menu isn't where this page says, search the portal for the resource name.

## The map

```text
                      you: csai, or the Foundry playground
                                   │ Entra
             ┌─────────────────────▼──────────────────────┐
             │ Foundry project                            │
             │   model deployments ◄── hosted agent       │
             │                         rca-agent          │
             │   toolbox "diagnostics" ◄──┘               │
             └──────┬───────────────────┬─────────────────┘
                    │ function key      │ Entra
             MCP function app       AI Search index
                                    (historical cases)
   ── virtual network ──────────────────────────────────────────────
     agent (injected) ──► Cosmos DB (episodes) ◄── platform API ◄── csai episodes
   ─────────────────────────────────────────────────────────────────
                 everything ──► Application Insights / Log Analytics
```

| Part | Stops | Capabilities ([specification §5](specification.md)) |
|---|---|---|
| [1. Foundations](#part-1-foundations) | Resource group · Models · The hosted agent | C9, C2, C1 |
| [2. Tools, knowledge and memory](#part-2-tools-knowledge-and-memory) | Tools and toolbox · Knowledge · Episodes and feedback | C3, C4, C5 |
| [3. Trust and quality](#part-3-trust-and-quality) | Network and identity · Observability · Evaluation | C8, C6, C7 |

---

## Part 1: Foundations

### Stop 1: The resource group, or what one `azd up` built

**The idea.** The whole platform is declared in `infra/main.bicep` and its modules; nothing is created by hand. azd deploys the Bicep, and the Bicep outputs become the azd environment, which the hooks, `azure.yaml` and `csai` read. A second environment, in another subscription or region, is one `azd env new` away.

**Look.** In the Azure portal, open your resource group.

- Group the resources by type and match each one to a box on the map.
- Open **Settings → Deployments**. Each Bicep module is its own deployment (`foundry`, `cosmos`, `search`, `network` and so on), with its inputs, outputs and duration.

**Try.**

```bash
azd show
az resource list -g $RG --query "[].{type:type, name:name}" -o table
azd env get-values | cut -d= -f1     # setting names only
```

Some settings weren't produced by Bicep. `TOOLBOX_ENDPOINT` was written by a deployment hook, and `AGENT_RCA_AGENT_*` by the agent deployment.

**Check yourself.** (1) Why are the toolbox and its connections created by a script (`scripts/setup_platform.py`) instead of Bicep?

### Stop 2: Models as configuration

**The idea.** The agent never names a model; it reads the deployment name from `AZURE_AI_MODEL_DEPLOYMENT_NAME`. Model, version, SKU and capacity are Bicep parameters (`chatModel` and `embeddingModel` in `infra/main.bicep`). The SKU is **DataZoneStandard**: requests can be processed in any region of the data zone (the EU, for the default region), never outside it.

**Look.** In the Foundry portal, open your project's **Models** or **Deployments** page.

- The chat model serves the agent. The embedding model turns text into vectors for AI Search.
- Open the chat deployment and find its **rate limit** in tokens per minute. A diagnosis uses about 10–15k tokens, so a few parallel runs reach the default limit. That's why `csai eval` runs only three cases at a time and retries.

**Try.**

```bash
az cognitiveservices account deployment list -g $RG -n $AZURE_AI_ACCOUNT_NAME \
  --query "[].{name:name, model:properties.model.name, version:properties.model.version, sku:sku.name, capacity:sku.capacity}" -o table
```

**Check yourself.** (2) You want to try a different chat model. What do you change, and which command shows that the agent still meets its quality bar?

### Stop 3: The hosted agent

**The idea.** `rca-agent` is our own container: Microsoft Agent Framework plus the platform library `cs-platform`, served on the Responses protocol by `ResponsesHostServer`. Foundry runs it and provides the endpoint, sessions, scaling and an Entra **identity per agent**. Our code provides the behavior (instructions and output schema) and the episode capture. Every `azd deploy rca-agent` builds a new image in the container registry and creates a new **agent version**.

**Look.**

- In the Foundry portal, open **Agents → rca-agent**:
  - **Versions:** one per deployment.
  - The **container** settings: image, CPU and memory, environment variables. `TOOLBOX_ENDPOINT` and `COSMOS_*` are how the agent finds its tools and its store.
  - The **playground**: paste an input from [`cases.jsonl`](../evals/rca/src/rca_evals/cases.jsonl) and watch the tool calls.
- In the Azure portal, open the container registry's **Repositories**. There's one tag per deployment, and each image was built in Azure from the repository, not on your machine.

**Try.**

```bash
azd ai agent show rca-agent
```

Run a diagnosis ([walkthrough step 2](walkthrough.md#2-diagnose-it)), then read the agent's code. Its behavior lives in three files:

- [`instructions.md`](../agents/rca/src/rca_agent/instructions.md): how the agent investigates, and the rules for its answer.
- [`report.py`](../agents/rca/src/rca_agent/report.py): the `RcaReport` schema, enforced as strict structured output.
- [`main.py`](../agents/rca/src/rca_agent/main.py): the hosted entry point. It's a few lines; the hosting server does the rest.

**Check yourself.** (3) The agent's identity only exists after the first deployment. What does that identity need, and what grants it?

---

## Part 2: Tools, knowledge and memory

### Stop 4: Tools and the toolbox

**The idea.** Diagnostic data sources are exposed as read-only **MCP tools** by a server on Azure Functions (`services/diagnostics-mcp`). They are `get_machine_context`, `get_error_events`, `get_telemetry_window`, `lookup_error_code` and `get_logbook`. Agents don't connect to that server directly. They use a Foundry **toolbox**, one MCP endpoint that bundles the tools with AI Search and holds the credentials in project connections. The MCP server's function key sits in a Foundry connection and never reaches the agent or your machine.

**Look.**

- In the Foundry portal, open the project's **connected resources** (management center or project settings). `diagnostics-mcp` uses a custom key, and `diagnostics-search` uses Entra.
- In the Azure portal, open the MCP function app: **Functions** lists one MCP tool trigger per tool. **Settings → Networking** shows the VNet integration.

**Try.**

```bash
# What the agent gets: the toolbox definition the deployment hook publishes
sed -n '/^def toolbox_definition/,/^def /p' scripts/setup_platform.py
```

Then open an episode ([walkthrough step 4](walkthrough.md#4-review-the-episode)). Tool names arrive prefixed with the server label, and every call's duration is recorded. The durations show the cost of the toolbox hop: each call takes several seconds through the toolbox, against about 50 ms when the agent calls the MCP server directly. It's in the [backlog](iteration-2-backlog.md).

To work with the tools themselves, run the MCP server locally and open it in the MCP Inspector ([`services/diagnostics-mcp/README.md`](../services/diagnostics-mcp/README.md#run-locally)). Call `get_telemetry_window` for `M-0007` and `purge_gas_flow_slm`, and look for the trend and the first out-of-tolerance reading.

**Check yourself.** (4) Why do tool results carry refs such as `EV-001234` and `TS:M-0007:purge_gas_flow_slm`, and what checks them?

### Stop 5: Knowledge grounding

**The idea.** Historical cases (symptom, root cause, resolution) live in an AI Search index with three kinds of retrieval: **keyword**, **vector** and **semantic** ranking. The search service turns your query text into a vector with the Foundry embedding model (an integrated *vectorizer*), using its own managed identity, so no client computes embeddings. The deployment hook `seed-search` creates and fills the index; its definition is `index_definition()` in `scripts/setup_platform.py`.

**Look.** In the Azure portal, open the search service: **Indexes → diagnostics-cases → Search explorer**. Switch to the JSON view and run the same sentence two ways. First as a keyword query:

```json
{ "search": "the nitrogen flushing seems weaker every day", "select": "id,title,failure_mode_id", "top": 5 }
```

Then as a vector query:

```json
{ "vectorQueries": [{ "kind": "text", "text": "the nitrogen flushing seems weaker every day", "fields": "content_vector", "k": 5 }],
  "select": "id,title,failure_mode_id" }
```

The keyword query matches words like "every" and "day" and returns unrelated cases. The vector query shares no words with the purge-gas cases and returns five of them (`FM-07`). That's what the vectors add. Try `"queryType": "semantic", "semanticConfiguration": "default"` with a keyword query too: semantic ranking reorders the keyword results by meaning.

**Try.** The same query from the command line, with your Entra sign-in instead of a key:

```bash
az rest --method post --resource https://search.azure.com \
  --url "https://$AZURE_SEARCH_NAME.search.windows.net/indexes/$AZURE_SEARCH_INDEX_NAME/docs/search?api-version=2024-07-01" \
  --body '{"vectorQueries":[{"kind":"text","text":"the nitrogen flushing seems weaker every day","fields":"content_vector","k":5}],"select":"id,title,failure_mode_id"}' \
  --query "value[].[failure_mode_id,title]" -o tsv
```

Then check how often the agent actually searches. `csai eval` reports `used_knowledge`, which is close to 0. The tool works, but the model rarely chooses to call it. Getting it used reliably is the top item in the [backlog](iteration-2-backlog.md).

**Check yourself.** (5) The search service needs a role on the Foundry account, and the Foundry project needs roles on the search service. What is each one for?

### Stop 6: Episodes and feedback

**The idea.** Every run becomes an **episode**: input, every tool call with its arguments, full result and duration, the structured report, token usage and trace ID. The platform writes it, not the model, so the record is accurate whatever the model says. Episodes are saved in Cosmos DB, one document per run (`cs_platform/capture.py` and `cs_platform/episodes.py`). Experts attach a verdict as **feedback**, which is the raw material for evaluation and learning.

**Look.**

- In the Azure portal, open the Cosmos DB account and then **Data Explorer**. It can't read the data: public network access is disabled (**Settings → Networking**), so only clients inside the virtual network reach it. That's intentional ([ADR 0003](adr/0003-private-data-stores.md)).
- So episodes are read through the **platform API**, a function app inside the network. In the Azure portal, open it and look at **Functions** (`list_episodes`, `get_episode`, `add_feedback`) and **Settings → Networking**.

**Try.** Review an episode and record a verdict ([walkthrough steps 4 and 5](walkthrough.md#4-review-the-episode)). Behind `csai`, the API reads Cosmos DB as its own managed identity, and feedback is a patch of one field (`/feedback`), so the record the platform wrote is never rewritten.

**Check yourself.** (6) A diagnosis succeeds, but Cosmos DB is unreachable at that moment. What does the user see, and where would you notice the problem?

---

## Part 3: Trust and quality

### Stop 7: Network and identity

**The idea.** Data stores are private; control planes are public but Entra-only.

- **Private:** Cosmos DB and the functions' storage are reachable only through private endpoints in `snet-private-endpoints`, with private DNS zones. The function apps reach them through VNet integration (`snet-functions`). The hosted agent runs in `snet-agents` through Foundry **agent network injection**, which can only be set when the Foundry account is created.
- **Public, Entra only:** Foundry, the registry and AI Search have key auth disabled, so you can still deploy from a laptop.

Every caller has its own Entra identity with the narrowest roles that work; the full table is in [architecture → identities](architecture.md#identities-and-access).

**Look.**

- The virtual network's **Subnets** (note the delegations) and **Connected devices** (the private endpoints).
- **Private DNS zones** such as `privatelink.documents.azure.com`, with an A record for Cosmos DB pointing at a private IP.
- **Access control (IAM)** on the search service, the Foundry account and the registry.
- Cosmos DB data roles are *not* in the IAM blade: they're Cosmos DB's own role assignments. See the commands below.

**Try.**

```bash
az network private-endpoint list -g $RG --query "[].{name:name, target:privateLinkServiceConnections[0].groupIds[0]}" -o table
az cosmosdb show -g $RG -n $COSMOS_ACCOUNT_NAME --query "{public:publicNetworkAccess, localAuthDisabled:disableLocalAuth}"
az cosmosdb sql role assignment list -g $RG -a $COSMOS_ACCOUNT_NAME --query "[].principalId" -o tsv
```

Match the principal IDs from the Cosmos DB role assignments to the identities: the platform API's managed identity, the agent identity (`AGENT_RCA_AGENT_INSTANCE_IDENTITY_*` in `azd env get-values`) and you.

**Check yourself.** (7) Which two places still use a key instead of Entra, and who holds each key?

### Stop 8: Observability

**The idea.** The agent, the MCP server and the platform API send OpenTelemetry traces and logs to Application Insights, using the Microsoft OpenTelemetry distro, and Foundry adds its own spans for the Responses layer. Each episode records its trace ID, which is the `operation_Id` in Application Insights. So you can go from an expert's verdict to the exact model and tool calls behind it.

**Look.**

- In the Foundry portal, open **rca-agent → Traces** or **Monitoring**.
- In the Azure portal, open Application Insights:
  - **Application map** for the parts and the calls between them.
  - **Transaction search** for single runs.
  - **Logs** for the queries below.

**Try.** Run these in **Logs**, or from the command line with `az monitor app-insights query --app $APPI -g $RG --analytics-query "<query>"`.

```kusto
// Who reports telemetry: rca-agent, Foundry's Responses layer, the two function apps
union requests, dependencies, traces
| where timestamp > ago(1d)
| summarize items = count() by cloud_RoleName, itemType
```

Then follow a single run with the query in [walkthrough step 4](walkthrough.md#4-review-the-episode). It shows the run step by step: the `invoke_agent` request, `chat <model>` for each model turn, and `execute_tool` and `tools/call` for each tool. The durations show where the time goes. Model turns take a few seconds, and toolbox calls often take longer. Across runs:

```kusto
// Average time per model turn and per tool, across runs
dependencies
| where timestamp > ago(1d) and cloud_RoleName == "rca-agent"
| summarize calls = count(), avg_ms = avg(duration) by name
| order by avg_ms desc
```

**Check yourself.** (8) Why does the episode store the trace ID, when Application Insights already has the traces?

### Stop 9: Evaluation as a quality gate

**The idea.** Quality is measured, not assumed. A versioned **case manifest** ([`cases.jsonl`](../evals/rca/src/rca_evals/cases.jsonl), 18 synthetic incidents with the expected root cause) is scored by plain-code evaluators ([`evaluators.py`](../evals/rca/src/rca_evals/evaluators.py)), run by the platform's harness (`cs_platform/evals.py`). Each gated metric has a minimum in [`thresholds.yaml`](../evals/rca/src/rca_evals/thresholds.yaml), and `csai eval` exits 1 below any of them, so any pipeline can enforce it ([`docs/ci-cd.md`](ci-cd.md)). The same suite runs against the agent in-process (`--target local`) or the deployed one (`--target hosted`). The harness runs three cases at a time and retries cases that fail on rate limits.

**Look.** Nothing to see in the portal yet. Publishing eval runs to Foundry's evaluation view (`csai eval --publish`) is parked: it needs capability hosts, which this network-injected project doesn't have ([backlog](iteration-2-backlog.md)).

**Try.** Run the gate and the experiment that breaks it ([walkthrough steps 6 and 7](walkthrough.md#6-check-quality-with-the-eval-gate)). Then compare `--output results.jsonl` from a good run and a broken one: the per-case scores and tool calls show which cases failed and why.

**Check yourself.** (9) Why are thresholds set from a measured baseline rather than at 1.0 across the board, and why isn't a passing suite proof that the agent is good?

---

## Where to go next

- **Change something and follow it through** ([walkthrough step 7](walkthrough.md#7-change-the-agent-and-check-it-again)), then compare episodes and traces before and after.
- **Add an agent:** [`docs/onboarding-an-agent.md`](onboarding-an-agent.md).
- **See what's missing:** [`docs/iteration-2-backlog.md`](iteration-2-backlog.md).
- **Clean up** when you're done: `azd down --purge` (and set `AZURE_LOCATION` again before the next `azd up`).

## Answers

1. **Toolbox from a script.** It needs the MCP server's function key, which exists only after the function app is deployed. Bicep runs before deployment, so a `postdeploy` hook registers the connection and publishes the toolbox ([ADR 0005](adr/0005-infrastructure-as-code.md)).
2. **Another model.** Change the `chatModel` parameters and run `azd provision`. Then run `csai eval rca --target hosted` (or `--target local` first): the gate decides whether the new model is good enough. No code changes.
3. **Agent identity.** It needs the Cosmos DB data contributor role to write episodes. The `postdeploy` hook of `rca-agent` in `azure.yaml` grants it (`setup_platform.py grant-agent`), reading the identity's principal ID that azd recorded.
4. **Refs.** They let the report cite exactly which record supports each claim. `evidence_grounded` checks that every cited ref exists in the data and belongs to the machine, and the episode keeps the tool results the refs came from.
5. **Search roles.** The search service calls the embedding model to vectorize queries, so it needs Cognitive Services OpenAI User on the Foundry account. The project and account identities call the search service when the toolbox's `azure_ai_search` tool runs, so they need Search Service Contributor and Search Index Data Contributor on it.
6. **Store outage.** The user gets the diagnosis as usual: saving the episode is best effort and never fails the request. The agent logs "Could not save episode …" to Application Insights, and the episode is missing from `csai episodes list`.
7. **Keys.** The MCP server's function key, held only by the Foundry connection `diagnostics-mcp`. And the platform API's function key, which `csai` fetches at run time with your Azure sign-in, so access follows Azure RBAC. Both are in the backlog to replace with Entra.
8. **Trace ID.** Traces are telemetry: they can be sampled, and they're kept only for the workspace's retention period. Episodes are the durable, reviewable record. The trace ID connects the two, so from an expert's verdict you can go straight to the full trace while it's still kept.
9. **Thresholds.** Thresholds sit just below what a known-good agent achieves, so normal model variation doesn't fail the gate but a real regression does. A passing suite only shows that the agent handles these 18 cases. All of them are solved at baseline, so the suite catches regressions but can't show improvement; harder cases are in the backlog.
