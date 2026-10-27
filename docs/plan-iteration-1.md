# Sample: CS AI Platform on Azure (iteration 1)

## Context

The scenario (full description in `docs/specification.md`) is a **minimum viable CS AI platform** that turns diagnostic agent prototypes into production-grade agents. One RCA (root-cause analysis) workflow for field engineers validates the platform. The same document lists the candidate services.

This repository is a **runnable reference sample** that can be deployed to any Azure subscription. It explores the core services hands-on and gives a concrete starting point for architecture discussions.

**Goal:** Show, end to end in one subscription, the path from "agent prototype" to "agent on a governed platform". The platform provides model access, tools, knowledge grounding, telemetry, evaluation gates, an episode/feedback trail and repeatable deployment. A fictional RCA diagnostics agent proves it works.

**Decisions:**

- **European region by default:** `swedencentral`, overridable via the `AZURE_LOCATION` azd env value.
- **Model is a parameter, not a fixed choice.** Requirement: modern, relatively cheap, available in swedencentral as **DataZoneStandard (EU)** so prompts and responses stay in the EU. Default `gpt-5.4-mini` (mini tier; DataZoneStandard in swedencentral per Learn). Newer models such as `gpt-6.1-terra` are optional overrides (`azd env set AZURE_CHAT_MODEL ...`). Step 5 confirms the default against current pricing and subscription quota. Model name, version, SKU and capacity are Bicep parameters, and agent code reads the deployment name from config only.
- Foundry **hosted agent** built with **Microsoft Agent Framework (Python)**
- **Bicep + azd**
- **Typer CLI** plus the Foundry portal as the interface
- All data is **synthetic and fictional**: no real organizations, data or machine types

## Core value the sample demonstrates

1. **Platform, not one agent.** A reusable harness. Onboarding an agent means writing a spec, a prompt, a toolbox reference and an eval suite.
2. **Evidence-backed RCA.** Ranked root-cause hypotheses, each citing tool and knowledge evidence, in structured output.
3. **Observability.** End-to-end OpenTelemetry traces (agent, model, MCP tool calls) in Application Insights and Foundry.
4. **Evaluation as a quality gate.** A versioned case manifest and evaluators, with thresholds enforced by `csai eval` (non-zero exit on regression), ready to run in any CI.
5. **Inner feedback loop.** Every run is stored as a structured episode, and an expert correction can be attached to it.
6. **Developer pathway.** uv, ruff, pyright, pytest with pre-commit hooks; `azd up`. CI/CD is documented but not active in this exploration repo (`docs/ci-cd.md`).

## Architecture (iteration 1)

```
Typer CLI ──(Responses API, Entra)──► Foundry hosted agent "rca-agent" (MAF + platform harness, container)
                                          │  model: Foundry deployment (parameterized, default gpt-5.4-mini, DataZoneStandard EU)
                                          │  tools: Foundry Toolbox "diagnostics" (one MCP endpoint)
                                          │           ├─ MCP server on Azure Functions (Flex): machine context,
                                          │           │   error events, telemetry window, error-code lookup
                                          │           └─ Azure AI Search: logbook entries + historical cases
                                          ├─ episode capture (harness middleware) ──► Cosmos DB (episodes, feedback)
                                          └─ OTel ──► Application Insights / Log Analytics ◄── Foundry tracing + evals
```

Azure resources (one resource group, default `swedencentral`; all resources in the same EU region):

- Foundry account + project + model deployment
- ACR
- Application Insights + Log Analytics
- AI Search (Basic)
- Cosmos DB NoSQL (serverless)
- Function App (Flex Consumption) + storage
- User-assigned identities where needed

Access is Entra/RBAC only: no keys in code, and `disableLocalAuth` where the service supports it.

Deferred to iteration 2:

- APIM AI gateway
- Private networking
- Outer feedback loop (SME approval and replay via Logic Apps, agent optimizer)
- Content Understanding ingestion
- Fabric / ADX telemetry
- Purview, Defender
- Teams / Copilot Studio channel
- Mistral comparison
- Multi-agent workflows
- Edge

## Repository layout (uv workspace)

```
pyproject.toml            # workspace root; ruff, pyright, pytest config; dev deps
.python-version  .pre-commit-config.yaml  azure.yaml   # uv.lock stays local (gitignored)
packages/
  cs-platform/            # the reusable harness: settings, telemetry, agent spec loader,
                          #   agent factory, episode model + store (Cosmos / in-memory), RCA output schema
  diagnostics-domain/     # synthetic domain models + deterministic data generator + seed data
agents/rca/               # hosted agent: main.py, agent.spec.yaml, instructions.md, Dockerfile
services/diagnostics-mcp/ # Azure Functions MCP server (tools over the synthetic domain data)
evals/rca/                # cases.jsonl (case manifest), evaluators, thresholds.yaml
cli/                      # `csai` Typer CLI: diagnose, episodes list/show, feedback, eval
infra/                    # main.bicep + modules/{monitoring,foundry,search,cosmos,functions,rbac}.bicep
scripts/                  # azd hooks: seed AI Search index, grant agent identity data roles
docs/                     # architecture.md, onboarding-an-agent.md, adr/, iteration-2-backlog.md
```

## Implementation order

Each step ends green: lint, type check and tests pass, and the step is committed.

**0. Foundations**
- Set up the uv workspace with the latest Python (target 3.14; fall back to 3.13 if MAF, the Azure SDKs or hosted agents lag, and record that in an ADR).
- Tooling: ruff (lint + format), pyright (strict on `packages/`), pytest + pytest-asyncio, pre-commit.
- Commands documented in the README (`uv run ruff check`, `uv run pyright`, `uv run pytest`).
- No CI pipeline (exploration repo): pre-commit hooks run lint, format and type checks; `uv.lock` stays local (ADR 0002).

**1. Synthetic domain (`diagnostics-domain`)**
- Pydantic models: Machine, ErrorEvent, TelemetrySeries, LogbookEntry, HistoricalCase, FailureMode.
- A seeded, deterministic generator for about 8 fictional failure modes (e.g. stage-temperature drift, vacuum leak, laser energy instability), each with consistent signals across events, telemetry, logbooks and past cases.
- Committed seed JSON; unit tests check consistency.

**2. Diagnostics MCP server (`services/diagnostics-mcp`)**
- Python Azure Functions app with the MCP extension.
- Read-only tools: `get_machine_context`, `get_error_events`, `get_telemetry_window`, `lookup_error_code`, backed by the seed data.
- Tests call the tool functions directly; run locally with `func start` and the MCP inspector.

**3. Platform harness (`cs-platform`)**
- `AgentSpec` (YAML): name, instructions file, model deployment, toolbox name, output schema, eval suite.
- Telemetry bootstrap (Microsoft OpenTelemetry distro, MAF spans).
- `RcaReport` output schema: ranked hypotheses with confidence, evidence items (source, ref, excerpt) and recommended checks.
- Episode model and `EpisodeStore` protocol, with Cosmos and in-memory implementations.
- MAF middleware that records tool calls, evidence and the final report into an episode, deterministically and outside the LLM's control.
- Tests use the in-memory store and a fake chat client.

**4. RCA agent (`agents/rca`)**
- MAF agent built through the harness, served with the hosted-agent Responses host.
- Instructions require cited evidence and a structured `RcaReport`.
- Runs locally with `azd ai agent run` against a local MCP server.
- Uses **container deploy mode**, with a uv-based Dockerfile, so the workspace packages build reliably.

**5. Infrastructure (`infra/`, `azure.yaml`)**
- Bicep modules for all the resources above. RBAC:
  - project MI: Foundry User, ACR pull, Log Analytics reader
  - dev user: Foundry User / Project Manager, Cosmos data contributor, Search index contributor
  - Functions MI: storage access
- azd hooks:
  - `postprovision`: create and seed the AI Search index (logbooks and cases, with integrated vectorization or script embeddings)
  - `postdeploy`: grant the hosted agent's identity the Cosmos data role, using its object ID after deployment
- Goal: `azd up` works from a clean subscription.

**6. Toolbox wiring**
- An `azure.ai.toolbox` service in `azure.yaml` bundles the MCP server connection and the `azure_ai_search` tool. The agent consumes it via `uses:` or `TOOLBOX_ENDPOINT`.
- MCP auth: start with a key-based project connection (secret held by Foundry), then harden to Entra (project MI + Functions built-in auth) as the last task of this step if feasible. Otherwise move it to the iteration 2 backlog.

**7. Evaluation gate (`evals/rca`)**
- `cases.jsonl`: about 15–20 synthetic cases with the expected root cause.
- Evaluators:
  - code-based: root-cause hit@1 and hit@3, evidence present and citing real refs, schema validity
  - built-in Foundry: task adherence, tool-call accuracy, groundedness
- `thresholds.yaml` sets the pass criteria. `csai eval` runs the suite against a local or deployed agent, publishes the run to Foundry, and exits non-zero on regression.

**8. CLI (`cli/`)**
- `csai diagnose <machine-id> "<symptom>"` renders the hypotheses and evidence and prints the episode ID.
- `csai episodes list/show`.
- `csai feedback <episode-id> --verdict --actual-root-cause --note` writes the expert correction to Cosmos.

**9. CI/CD (documented, not active)**
- `docs/ci-cd.md` maps the local gates to a pipeline: quality checks and `csai eval` on pull requests, `azd provision` + `azd deploy` with OIDC on merge, plus a smoke test. Nothing is wired up in this repo.

**10. Docs**
- README quickstart (prerequisites, `azd up`, demo script).
- `architecture.md` with a mermaid diagram mapping each component to a platform outcome.
- `onboarding-an-agent.md`.
- ADRs for hosting, IaC and Python version.
- `iteration-2-backlog.md`.

## Risks / verify early

- **Preview features:** hosted agents, toolboxes, tracing and agent identity are partly in preview. Pin the azd extension and SDK versions and record them in an ADR.
- **Region, model and quota.** Before writing all the Bicep in step 5:
  - Confirm the default model's price and quota in swedencentral (DataZoneStandard). Keep it if it's cheap and has quota; otherwise pick another modern, low-cost swedencentral model and record why in an ADR.
  - Confirm that hosted agents, toolboxes and AI Search are available in swedencentral. Fallback EU regions: francecentral, germanywestcentral.
- **Embeddings for AI Search:** `text-embedding-3-large`, DataZoneStandard EU (available in swedencentral).
- **Agent identity → Cosmos RBAC:** the identity exists only after deploy, hence the `postdeploy` hook. Validate this in step 5 or 6.
- **Functions MCP Entra auth** needs an Entra app registration (Graph Bicep extension); this is the reason for the key-first fallback.

## Verification (end to end)

1. `uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest`: all green locally (pre-commit runs the first three on every commit).
2. `azd up` from a fresh environment succeeds. The `postprovision` hook seeds the Search index, and `postdeploy` assigns the agent's roles.
3. `csai diagnose M-0042 "stage temperature alarm after PM"` returns ranked hypotheses with evidence referencing real seed records.
4. The Foundry portal shows the trace tree: agent → model → toolbox/MCP tool calls → AI Search.
5. `csai episodes show <id>` shows the stored episode. `csai feedback <id> ...` attaches a correction, visible in Cosmos.
6. `csai eval` passes its thresholds. A deliberately broken instruction (e.g. removing the evidence requirement) makes it fail, which proves the gate works. The run is visible in Foundry evaluations.
7. After any change to `agents/rca`, re-running `csai eval` is the merge gate; `docs/ci-cd.md` shows how a pipeline would enforce it.
