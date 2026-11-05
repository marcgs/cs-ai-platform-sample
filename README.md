# CS AI Platform sample

A reference sample that shows the path from **an agent prototype** to **an agent running on a governed Azure platform**. The platform gives agents model access, tools, knowledge grounding, telemetry, an episode and feedback trail, evaluation and repeatable deployment. A fictional root-cause-analysis (RCA) diagnostics agent proves it works.

> All data in this repository is **synthetic and fictional**: no customer data, names or machine types.

| Read | For |
|---|---|
| [Foundry findings](docs/foundry-findings.md) | What we hit on Foundry, Agent Framework and azd, and how we got past it |
| [Walkthrough](docs/walkthrough.md) | One case end to end on the deployed platform, and where to look in Azure |
| [Architecture](docs/architecture.md) | How the parts fit together |
| [Specification](docs/specification.md) | What the platform must do, and what's out of scope |
| [ADRs](docs/adr/) · [backlog](docs/backlog.md) | Decisions · ideas for later |
| [Onboarding an agent](docs/onboarding-an-agent.md) | Adding a second agent |
| [AGENTS.md](AGENTS.md) | Rules, commands and gotchas for changing the code |

## What runs where

- **Microsoft Foundry:** model deployments (gpt-5.4-mini and text-embedding-3-large, EU data zone), the hosted agent `rca-agent` (Agent Framework, our container), the `diagnostics` toolbox (MCP tools and AI Search), and evaluation.
- **Azure Functions:** the diagnostics MCP server, and the platform API for episodes and feedback.
- **Data:** Cosmos DB for episodes (private), AI Search for historical cases.
- **Your machine:** `azd` to provision, deploy, run, invoke and evaluate the agent; `csai` to read episodes and record expert feedback.

## Quickstart

**Prerequisites:** [uv](https://docs.astral.sh/uv/) 0.13+ (installs Python 3.14), [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/) 1.37+ with `azd extension install microsoft.foundry`, the [Azure CLI](https://learn.microsoft.com/cli/azure/), [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) (to run the MCP server locally), and a subscription where you can create resources and role assignments (Owner, or Contributor plus Role Based Access Control Administrator). If your machine must use a package mirror, configure it in your user-level uv configuration, never in this repository ([ADR 0002](docs/adr/0002-local-lock-files.md)).

```bash
uv sync --all-packages
uv run pre-commit install

azd auth login && az login
azd env new cs-platform-dev
azd env set AZURE_LOCATION swedencentral
azd env set AZURE_SEARCH_LOCATION northeurope   # optional: if AI Search has no capacity there
azd up                                          # about 20 minutes
```

`azd up` provisions everything with Bicep, deploys the function apps and the hosted agent, and runs the hooks that seed search, publish the toolbox and grant the agent access ([architecture](docs/architecture.md#deployment)).

Try it:

```bash
azd ai agent invoke "M-0007: Pressure excursions in the chamber, purge flow looks lower than normal."
uv run csai episodes list
```

The agent answers with ranked hypotheses and their evidence, and the platform records the run as an episode. The [walkthrough](docs/walkthrough.md) takes it from there.

### Evaluate

```bash
azd extension install azure.ai.evaluations   # once
azd ai eval create rca-quality               # once per environment, and after changing evals/azure.eval.yaml

RUN_NAME="rca-agent-$(azd env get-value AGENT_RCA_AGENT_VERSION)-$(date +%F)"
azd ai eval run start --no-wait --name "$RUN_NAME"
uv run python -m rca_evals.gate --run "$RUN_NAME"   # once the run has completed
```

Foundry sends the 50 test cases to the deployed agent and scores the answers; the gate reads the saved results and prints PASS or FAIL. A run costs about $1, so check the [known evaluation failures](docs/foundry-findings.md#agent-target-evaluations-can-lose-responses-mid-run) first. The [eval guide](evals/rca/README.md#evaluation) explains the evaluators, the gate and its baseline.

### Clean up

```bash
azd down --purge
```

While deployed, fixed costs are a few euros per day, mostly AI Search Basic and the private endpoints. Model usage is about 10–15k tokens per diagnosis.

## Development

```bash
uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest   # the gates, all offline
azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"         # the agent locally
azd ai agent invoke --local "M-0001: ..."                                            # one request to it
```

There's no CI pipeline: the pre-commit hooks are the gate ([CI/CD](docs/ci-cd.md)). To run the agent against the MCP server on your machine, see [`agents/rca`](agents/rca/README.md).

| Path | Purpose |
|---|---|
| `packages/cs-platform` | Platform harness: agent specs, episode capture and stores, telemetry |
| `packages/diagnostics-domain` | Synthetic domain, data generator and seed data |
| `agents/rca` | The RCA agent: spec, instructions, report schema, hosted entry point |
| `evals/rca` | Test cases with answer keys, evaluators and the gate |
| `services/diagnostics-mcp` | Read-only diagnostic tools as an MCP server |
| `services/platform-api` | Episodes and feedback over the private episode store |
| `cli` | `csai`: episodes and expert feedback |
| `infra`, `scripts` | Bicep for every resource; azd hooks |
