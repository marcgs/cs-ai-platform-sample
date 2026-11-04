# CS AI Platform sample

A reference sample that shows the path from **an agent prototype** to **an agent running on a governed Azure platform**. The platform gives agents model access, tools, knowledge grounding, telemetry, an episode/feedback trail and repeatable deployment. A fictional root-cause-analysis (RCA) diagnostics agent proves it works.

> All data in this repository is **synthetic and fictional**. It contains no customer data, names or machine types.

- What and why: [`docs/specification.md`](docs/specification.md) · [`docs/architecture.md`](docs/architecture.md)
- What we learned about Foundry, its limitations and how we got past them: [`docs/foundry-findings.md`](docs/foundry-findings.md)
- Using it, one case end to end: [`docs/walkthrough.md`](docs/walkthrough.md) · each part in Azure: [`docs/platform-tour.md`](docs/platform-tour.md)
- Decisions: [`docs/adr/`](docs/adr/) · ideas and what's next: [`docs/backlog.md`](docs/backlog.md)
- Adding an agent: [`docs/onboarding-an-agent.md`](docs/onboarding-an-agent.md)
- Changing the code (rules, commands, gotchas; for people and coding agents): [`AGENTS.md`](AGENTS.md)

> **Evaluation is being rebuilt** the way Foundry documents it (`azd ai eval`, built-in and custom evaluators). Two built-in judges and six code evaluators score the 50 test cases, the latter against each case's answer key ([Evaluate](#evaluate)). The earlier, self-built evaluation harness and the project's history are in the `before-cleanup` tag.

## What runs where

- **Microsoft Foundry:** model deployments (gpt-5.4-mini, text-embedding-3-large; EU data zone), the hosted `rca-agent` (Agent Framework, container), the `diagnostics` toolbox (MCP tools + AI Search) and its connections.
- **Azure Functions (Flex Consumption):** the diagnostics MCP server and the platform API for episodes and feedback.
- **Data:** Cosmos DB for episodes and AI Search for historical cases. Cosmos DB and the functions' storage are reachable only through private endpoints.
- **Observability:** Application Insights and Log Analytics.
- **Your machine:** `azd` to provision, deploy, run and invoke the agent; `csai` to read episodes and record expert feedback.

## Quickstart

### Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.13+ (installs Python 3.14)
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/) 1.37+ with the Foundry extensions: `azd extension install microsoft.foundry`
- [Azure CLI](https://learn.microsoft.com/cli/azure/) (templates use it for validation; `csai` and the hooks use your sign-in)
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local), to run the MCP server locally
- An Azure subscription where you can create resources and role assignments (Owner, or Contributor + Role Based Access Control Administrator)

If your machine must use a package mirror, configure it in your user-level uv configuration, never in this repository ([`docs/dependencies.md`](docs/dependencies.md)).

### Deploy

```bash
uv sync --all-packages
uv run pre-commit install

azd auth login && az login
azd env new cs-platform-dev
azd env set AZURE_LOCATION swedencentral
# optional: if AI Search has no capacity in that region
azd env set AZURE_SEARCH_LOCATION northeurope

azd up        # about 20 minutes on an empty subscription
```

`azd up` provisions everything with Bicep, seeds the search index, deploys both function apps, publishes the toolbox, builds the agent image in the registry, deploys the hosted agent and grants its identity access to the episode store. See [architecture → deployment](docs/architecture.md#deployment).

### Try it

```bash
azd ai agent invoke "M-0007: Pressure excursions in the chamber, purge flow looks lower than normal."
uv run csai episodes list
uv run csai episodes show <episode-id>
```

The agent answers with ranked hypotheses and their evidence, and the platform records the run as an episode. [`docs/walkthrough.md`](docs/walkthrough.md) takes it from there: questioning the answer in the playground, reviewing the episode and recording an expert verdict with `csai feedback`.

### Evaluate

```bash
azd extension install azure.ai.evaluations   # once
azd ai eval create rca-quality               # once per environment, and after changing evals/azure.eval.yaml

azd ai eval run start --no-wait --name "rca-agent-$(azd env get-value AGENT_RCA_AGENT_VERSION)-$(date +%F)"
```

Foundry sends the 50 test cases ([`evals/rca`](evals/rca/README.md#evaluation)) to the deployed agent and scores each answer twice: with the intent resolution and task adherence judges, and with six code evaluators that compare it with the case's answer key (`hit_at_1`, `hit_at_1_lenient`, `hit_at_3`, `decisive_evidence_recall`, `evidence_grounded`, `injection_resisted`). Results are in the Foundry portal under the project's evaluations, `rca-quality`, with per-case scores. All 50 cases take about 2.2M reported tokens and 25 minutes, but the agent calls currently stop working after about 14 minutes, so the last cases of a run fail and score 0 although the run says `completed` ([finding](docs/foundry-findings.md#an-evaluation-runs-agent-calls-stop-working-after-about-14-minutes)). Check the per-case results for agent errors before reading the scores. `--no-wait` is needed: azd can't read this evaluation's runs back yet, and each `create` adds another evaluation with the same name ([findings](docs/foundry-findings.md#evaluation)).

### Clean up

```bash
azd down --purge
```

Fixed costs while deployed are a few euros per day, mostly AI Search Basic and the private endpoints; model usage is pay-per-token (about 10–15k tokens per diagnosis).

## Development

```bash
uv run ruff check && uv run ruff format --check   # lint and format
uv run pyright                                     # types (strict for all source packages)
uv run pytest                                      # tests, all offline

azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"   # the agent locally, with the Agent Inspector
azd ai agent invoke --local "M-0001: ..."          # one request to the local agent
azd ai agent monitor --follow                      # the deployed agent's logs
```

`csai` reads its settings from the active azd environment. To run the agent against the MCP server on your machine instead of the toolbox, see [`agents/rca/README.md`](agents/rca/README.md).

There's no CI pipeline in this repository: the pre-commit hooks are the gate. [`docs/ci-cd.md`](docs/ci-cd.md) maps them onto a pipeline.

## Repository layout

| Path | Purpose |
|---|---|
| `packages/cs-platform` | The platform harness: agent specs, episode capture and stores, telemetry ([README](packages/cs-platform/README.md)) |
| `packages/diagnostics-domain` | Synthetic diagnostics domain, data generator and seed data |
| `agents/rca` | The RCA agent: spec, instructions, report schema, hosted entry point, image ([README](agents/rca/README.md)) |
| `evals/rca` | The RCA agent's test cases with their answer keys, generated from the seed scenarios ([README](evals/rca/README.md)) |
| `services/diagnostics-mcp` | Read-only diagnostic tools as an MCP server on Azure Functions ([README](services/diagnostics-mcp/README.md)) |
| `services/platform-api` | Episodes and feedback over the private episode store, on Azure Functions |
| `cli` | `csai`: episodes and expert feedback |
| `infra` | Bicep for every Azure resource (`main.bicep` + modules) |
| `scripts` | azd hooks: function packaging, search seeding, toolbox, agent access |
| `docs` | Specification, architecture, Foundry findings, ADRs, onboarding, backlog |

## Dependencies

`uv.lock` is local only (gitignored): everyone resolves against their own configured package index. Deployments install the locally locked versions: the function apps from prebuilt wheels, the agent image from an exported, hashed requirements file without index URLs. See [ADR 0002](docs/adr/0002-local-lock-files.md).
