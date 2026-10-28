# CS AI Platform sample

A reference sample that shows the path from **an agent prototype** to **an agent running on a governed Azure platform**. The platform gives agents model access, tools, knowledge grounding, telemetry, evaluation gates, an episode/feedback trail and repeatable deployment. A fictional root-cause-analysis (RCA) diagnostics agent proves it works.

> All data in this repository is **synthetic and fictional**. It contains no customer data, names or machine types.

- What and why: [`docs/specification.md`](docs/specification.md) · [`docs/architecture.md`](docs/architecture.md)
- How it was built: [`docs/plan-iteration-1.md`](docs/plan-iteration-1.md) · decisions in [`docs/adr/`](docs/adr/)
- Adding an agent: [`docs/onboarding-an-agent.md`](docs/onboarding-an-agent.md)
- What's next: [`docs/iteration-2-backlog.md`](docs/iteration-2-backlog.md)

## What runs where

- **Microsoft Foundry:** model deployments (gpt-5.4-mini, text-embedding-3-large; EU data zone), the hosted `rca-agent` (Agent Framework, container), the `diagnostics` toolbox (MCP tools + AI Search) and its connections.
- **Azure Functions (Flex Consumption):** the diagnostics MCP server and the platform API for episodes and feedback.
- **Data:** Cosmos DB for episodes and AI Search for historical cases. Cosmos DB and the functions' storage are reachable only through private endpoints.
- **Observability:** Application Insights and Log Analytics.
- **Your machine:** `csai`, the command line to diagnose, evaluate, and review episodes.

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
# Diagnose an incident with the hosted agent; prints the report and the episode ID
uv run csai diagnose "M-0007: Pressure excursions in the chamber, purge flow looks lower than normal."

# Review what happened, then record the expert's verdict
uv run csai episodes list
uv run csai episodes show <episode-id>
uv run csai feedback <episode-id> --verdict correct --actual-root-cause FM-07 --reviewer "field engineer"

# Run the quality gate against the deployed agent (exit 1 below thresholds)
uv run csai eval rca --target hosted
```

Or chat with `rca-agent` in the Foundry portal's playground (link in the `azd deploy` output). The 18 scenarios in [`cases.jsonl`](evals/rca/src/rca_evals/cases.jsonl) are good prompts; each lists the expected failure mode.

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

uv run csai eval rca --target local                # quality gate with the agent in-process
uv run csai diagnose "M-0001: ..." --target local  # one run, episode kept in memory
```

`csai` reads its settings from the active azd environment. To run the agent against the MCP server on your machine instead of the toolbox, see [`agents/rca/README.md`](agents/rca/README.md).

There's no CI pipeline in this exploration repository: pre-commit hooks and `csai eval` are the gates. [`docs/ci-cd.md`](docs/ci-cd.md) maps them onto a pipeline.

## Repository layout

| Path | Purpose |
|---|---|
| `packages/cs-platform` | The platform harness: agent specs, episode capture and stores, eval harness, telemetry ([README](packages/cs-platform/README.md)) |
| `packages/diagnostics-domain` | Synthetic diagnostics domain, data generator and seed data |
| `agents/rca` | The RCA agent: spec, instructions, report schema, hosted entry point, image ([README](agents/rca/README.md)) |
| `evals/rca` | The RCA eval suite: case manifest, thresholds, evaluators |
| `services/diagnostics-mcp` | Read-only diagnostic tools as an MCP server on Azure Functions ([README](services/diagnostics-mcp/README.md)) |
| `services/platform-api` | Episodes and feedback over the private episode store, on Azure Functions |
| `cli` | `csai`: diagnose, eval, episodes, feedback |
| `infra` | Bicep for every Azure resource (`main.bicep` + modules) |
| `scripts` | azd hooks: function packaging, search seeding, toolbox, agent access |
| `docs` | Specification, architecture, plan, ADRs, onboarding, backlog |

## Dependencies

`uv.lock` is local only (gitignored): everyone resolves against their own configured package index. Deployments install the locally locked versions: the function apps from prebuilt wheels, the agent image from an exported, hashed requirements file without index URLs. See [ADR 0002](docs/adr/0002-local-lock-files.md).
