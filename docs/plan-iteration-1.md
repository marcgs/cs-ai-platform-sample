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
- Virtual network with private endpoints and private DNS for Storage and Cosmos DB; the function app and the hosted agents join it through delegated subnets

Access is Entra/RBAC only: no keys in code, and `disableLocalAuth` where the service supports it. Storage and Cosmos DB are private (ADR 0003); Foundry, the registry and AI Search stay public so developers can deploy and run from outside the network.

Deferred to iteration 2:

- APIM AI gateway
- Private endpoints for Foundry, the registry, AI Search and Application Insights (needs in-network deployment runners)
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
- `AgentSpec` (YAML): name, version, instructions file, tool sources, eval suite. The model deployment comes from platform settings, and the output schema from the agent's code.
- Telemetry bootstrap (Microsoft OpenTelemetry distro, MAF spans).
- Generic `Evidence` item (source, ref, excerpt) for agents to cite. The RCA-specific `RcaReport` lives with the agent (step 4).
- Episode model and `EpisodeStore` protocol, with Cosmos and in-memory implementations.
- MAF middleware that records tool calls, evidence and the final report into an episode, deterministically and outside the LLM's control.
- Tests use the in-memory store and a fake chat client.

**4. RCA agent (`agents/rca`)**
- MAF agent built through the harness, served with the hosted-agent Responses host.
- Instructions require cited evidence and a structured `RcaReport`.
- Runs locally with `rca-local` against a local MCP server (any Foundry model deployment); `azd ai agent run` once `azure.yaml` exists (step 5).
- Uses **container deploy mode**, with a uv-based Dockerfile, so the workspace packages build reliably. The image is built remotely in ACR (step 5); a package mirror can be passed as a BuildKit secret for local builds.

**5. Infrastructure (`infra/`, `azure.yaml`)**
- Bicep for every resource (azd's standard Bicep provider). The Foundry part is based on the layer `azd ai agent init --infra=bicep` generates: AIServices account, project, model deployments, registry with project connection and AcrPull, plus an Application Insights connection.
- RBAC, no keys (local auth disabled on Foundry, Cosmos DB, AI Search, Storage):
  - project MI: AcrPull, Log Analytics Reader, Search Index Data Reader
  - dev user: Azure AI User, AcrPush, Cosmos data contributor, Search service and index data contributor
  - Functions identity: storage blob/queue/table data roles, Monitoring Metrics Publisher
- The MCP function app deploys without a remote build: `scripts/package_mcp.sh` (azd `prepackage` hook) installs Linux wheels, including the workspace packages, into `.python_packages`.
- Networking (ADR 0003): a virtual network with subnets for private endpoints, Flex VNet integration and Foundry agent network injection. Storage (blob, queue, table) and Cosmos DB have public access disabled and private endpoints. Agent network injection only applies when the Foundry account is created.
- Goal: `azd up` works from a clean subscription.

**6. Agent deployment and toolbox wiring**
- The hosted agent is an `azure.ai.agent` service in `azure.yaml`: a container built remotely in ACR from the repository root, injected into the agent subnet. A `prepackage` hook exports the local `uv.lock` to a hashed requirements file (no index URLs), so the image runs the locally tested versions.
- `scripts/setup_platform.py` holds the setup steps, run as azd hooks:
  - `seed-search` (`postprovision`): creates the `diagnostics-cases` index (keyword, semantic and vector search; a Foundry vectorizer embeds queries) and loads the historical cases.
  - `connect-tools` (`postdeploy` of the MCP server): stores the function key in a `diagnostics-mcp` project connection and publishes the `diagnostics` toolbox (MCP server + `azure_ai_search`); sets `TOOLBOX_ENDPOINT`.
  - `grant-agent` (`postdeploy` of the agent): gives the agent identity the Cosmos DB data role.
- The AI Search connection is Entra-based (Bicep). The Foundry account and project identities get the Search roles; the search service's identity may call the embedding deployment.
- MCP auth stays key-based, with the key held only by Foundry. Entra (built-in auth on the function app) needs an app registration and moves to the iteration 2 backlog.

**7. Evaluation gate (`evals/rca`, `csai eval`)**
- Generic harness in `cs_platform.evals`: case manifest, evaluators (plain functions), thresholds, a runner with concurrency, retries with backoff for transient failures, and a gate that reports errored cases separately from metric failures.
- `evals/rca` (package `rca-evals`): `cases.jsonl` derived from the 18 seed scenarios (regenerated with `python -m rca_evals.manifest`, checked by a test), `thresholds.yaml`, and code-based evaluators: `schema_valid`, `hit_at_1`, `hit_at_3`, `evidence_grounded` (cited refs exist and belong to the machine), `tool_coverage` (diagnostic tools called), and `used_knowledge` (informational).
- `csai eval rca --target local|hosted` runs the suite against the in-process agent or the deployed hosted agent and exits 1 below a threshold. `--publish` also creates a Foundry eval run scored by built-in evaluators (task adherence, intent resolution, coherence), with the code metrics as columns; publishing reports, the code metrics gate.
- Baseline (gpt-5.4-mini, toolbox, 18 cases): 1.00 on every gated metric except `tool_coverage` 0.97, locally and hosted. With the investigation steps removed from the instructions, `hit_at_1` fell to 0.67 and `tool_coverage` to 0.77, failing the gate.
- Publishing to Foundry Evaluations is blocked in this environment: with agent network injection, cloud evaluations need account- and project-level capability hosts (and evaluation storage), which can only be set when the project is created. `--publish` reports the failure as a warning; the code-based gate is unaffected. Moved to the iteration 2 backlog.
- Findings: about 1 in 6 hosted runs fail on the first attempt (model rate limit inside the agent; the 50k TPM deployment is shared by parallel runs); the agent almost never searches historical cases (`used_knowledge` 0.00-0.06).

**8. CLI (`cli/`)**
- `csai diagnose <machine-id> "<symptom>"` renders the hypotheses and evidence and prints the episode ID.
- `csai episodes list/show`.
- `csai feedback <episode-id> --verdict --actual-root-cause --note` attaches the expert correction to the episode. Cosmos DB is private, so the CLI goes through a platform endpoint rather than writing to Cosmos directly.

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
