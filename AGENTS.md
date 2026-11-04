# Working in this repository

Guidance for coding agents (and people) who change this repository. Read [`README.md`](README.md) for what the sample is and [`docs/architecture.md`](docs/architecture.md) for how the parts fit together. This file covers the rules, the commands and the things that aren't obvious from the code.

## Hard rules

These come before anything else, including a request that seems to need an exception. If a task seems to need breaking one, stop and ask.

1. **Keep the repository organization-neutral.** Never name a real customer, partner or employer, and never name the company the authors work for. That applies to code, data, docs, commit messages and branch names. Product and service names (Azure, Foundry, Agent Framework, Python packages) are fine. All domain data is synthetic and fictional: machines `M-0001…`, failure modes `FM-01…`, no real machine types.
2. **Never commit environment specifics.** That means subscription or tenant IDs, azd environment tokens or resource names from a deployed environment, endpoints, keys, email addresses, and package index or mirror URLs. These belong in the azd environment (`.azure/`, gitignored), in `.env` (gitignored) or in user-level config.
3. **`uv.lock` is never committed**, and no index URL goes in a tracked file ([ADR 0002](docs/adr/0002-local-lock-files.md), [`docs/dependencies.md`](docs/dependencies.md)). Some machines can only reach an internal mirror, which is configured in the user's `~/.config/uv/uv.toml`. Generated lock exports (`agents/rca/requirements.lock.txt`) stay gitignored too.
4. **Before every commit, check what you're staging** (`git diff --cached`) for any of the above. Treat a hit as a blocker: if it is already in history, tell the user rather than committing on top.
5. **Don't change shared Azure state on your own.** Applying infrastructure or deployments (`azd up`, `azd provision`, `azd deploy`), creating role assignments outside Bicep, opening network access, and anything destructive (`azd down`, deleting, purging) are for the user to run or explicitly approve. Read-only checks are fine (`az bicep build`, `az deployment sub validate`/`what-if`, `azd env get-values`, `az … show/list`). The same goes for `git push`.
6. **No CI pipeline.** The pre-commit hooks and the commands below are the gates; don't add workflow files ([`docs/ci-cd.md`](docs/ci-cd.md)).

## Commands

```bash
uv sync --all-packages                 # once, and after changing any pyproject.toml
uv run pre-commit install              # once: ruff + pyright on every commit

uv run ruff check && uv run ruff format --check
uv run pyright                         # strict for every source package and scripts/
uv run pytest                          # offline: no Azure, no network, no model
uv run pytest agents/rca -k golden     # one package / one test

azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"
                                       # the agent locally (uses Azure models + toolbox)
azd ai agent invoke --local "M-0007: ..."
azd ai agent invoke "M-0007: ..."      # the deployed agent
uv run csai episodes list              # recorded runs; csai feedback records an expert verdict
```

Every change must leave ruff, pyright and pytest green. After changing agent instructions, schemas, tools or platform capture, try a few cases against the agent (`azd ai agent run` with the start command above, then `invoke --local`); it needs a deployed environment and costs tokens, so mention it when you skip it. Evaluation is being rebuilt the way Foundry documents it ([`docs/plan-evaluation.md`](docs/plan-evaluation.md)); until then there's no quality gate.

Regenerated files are checked by tests. Regenerate them rather than editing by hand:

```bash
uv run generate-seed-data                  # packages/diagnostics-domain/.../data/seed.json
uv run python -m rca_evals.manifest        # evals/rca/.../cases.jsonl (from the seed scenarios)
uv run python -m rca_evals.assets          # evals/rca/queries.jsonl and evaluators/*.json (from the cases and graders)
```

## Where things go

| Change | Where | Also update |
|---|---|---|
| Shared agent plumbing (spec, capture, episodes, telemetry) | `packages/cs-platform` | its README |
| Synthetic data, failure modes | `packages/diagnostics-domain` (`catalog.py`, `generator.py`) | regenerate seed + cases |
| RCA behavior | `agents/rca/src/rca_agent/instructions.md`, `report.py`, `agent.spec.yaml` | try a few cases |
| Diagnostic tools | `services/diagnostics-mcp` (`TOOL_NAMES`, tool functions) | the agent's instructions |
| Episodes and feedback API | `services/platform-api` | `cli/src/csai/platform.py` |
| CLI (episodes and feedback only; azd does the rest) | `cli/src/csai` | README "Try it" |
| Test cases | generator in `evals/rca`, scenarios in `packages/diagnostics-domain` | regenerate, don't hand-edit |
| Azure resources | `infra/main.bicep`, `infra/modules/*.bicep` | outputs → `azure.yaml` / `csai` |
| Data-plane setup Bicep can't do | `scripts/setup_platform.py` (azd hooks; idempotent) | `azure.yaml` hooks |
| A new agent | follow [`docs/onboarding-an-agent.md`](docs/onboarding-an-agent.md) | |

A new workspace package goes in the root `pyproject.toml` too: in `dependencies` and `[tool.uv.sources]`, and in the ruff `src`, pyright `strict` and pytest `testpaths` globs if it doesn't match the existing ones.

## Code conventions

- **Platform first.** Use what Foundry, Agent Framework and azd provide, following their documentation. Write our own code only for a gap that's proven and recorded in [`docs/foundry-findings.md`](docs/foundry-findings.md).
- **Python 3.14** everywhere ([ADR 0001](docs/adr/0001-python-version.md)). Annotations are deferred. When something inspects a signature at runtime, as the hosted-agent server does on `agent_factory`, import those types at runtime and add `# noqa: TC002`. A test (`test_hosting_server_accepts_the_factory`) guards this for the RCA agent.
- **Typing:** pyright strict. Avoid `Any` and `cast` unless an SDK forces them, and keep those to the boundary. Pydantic models for anything that crosses a boundary (tool results, reports, episodes, API bodies). Output schemas use `extra="forbid"` with all fields required, for strict structured outputs.
- **Azure access is Entra only**: `DefaultAzureCredential`/`AzureCliCredential`, never keys in code or settings. The two function keys are exceptions, fetched at runtime with ARM (the toolbox connection; `csai` → platform API) and listed in the backlog to replace.
- **Settings come from the environment.** Bicep outputs become azd environment values, which `azure.yaml`, the hooks and `csai` read (`cli/src/csai/environment.py`). Add a Bicep output instead of hard-coding a name.
- **Tests are offline.** Use `cs_platform.testing.ScriptedChatClient` to run the real tool loop with scripted model turns, the in-memory episode store, and the seed data. Don't mock what you can run.
- Match the surrounding style: small modules, docstrings on public functions, comments that explain *why*. Ruff's rule set is in the root `pyproject.toml`.
- Docs are plain and specific: short sentences, real commands, no marketing. Record a decision with real trade-offs as a new ADR in `docs/adr/` (next number, same format). Ideas go in the backlog, platform limitations in the findings (below).

## Backlog, findings and plans

- [`docs/backlog.md`](docs/backlog.md) keeps ideas for later, by theme and with stable IDs. It's not a to-do list: don't implement a backlog item unless the user asks for it.
- When work turns up an idea or a gap outside the current scope, add it to the backlog instead of doing it: the next free ID in the theme it fits and a rough size. Mention it to the user.
- When work hits a Foundry, Agent Framework or azd limitation, a preview bug or a docs inconsistency, add it to [`docs/foundry-findings.md`](docs/foundry-findings.md), with how we got past it and the date checked. Update an existing entry's status when you check it again.
- The user decides what's worked on. Larger work gets a short plan in `docs/plan-<topic>.md`; when it's done, its results go into the docs it changes and the plan is deleted. The repository describes the current state, not its history.

## Azure and deployment, the non-obvious parts

- **Topology:** Foundry, the registry and AI Search are public and Entra-only. Cosmos DB and the functions' storage are **private**, and an Azure Policy in the subscription forces their public access off ([ADR 0003](docs/adr/0003-private-data-stores.md)). From a laptop you can't reach Cosmos DB: local runs keep episodes in memory, and `csai episodes` goes through the platform API.
- **Agent network injection is set only when the Foundry account is created.** Changing `networkInjections` or the agent subnet means `azd down --purge` and `azd up`, which is the user's call. Foundry evaluation in this network needs the project capability host and the evaluation storage exception ([ADR 0008](docs/adr/0008-evaluation-storage-network-exception.md)), both in Bicep.
- **`azd down` clears `AZURE_LOCATION`** (and similar) from the environment. Set it again before the next `azd up`.
- **Function apps deploy prebuilt Linux wheels** (`scripts/package_function.sh`, `remoteBuild: false`): workspace packages aren't on any index, and installs use the locked versions with hashes. The agent image installs `agents/rca/requirements.lock.txt`, exported by the `prepackage` hook from the local `uv.lock`. A new runtime dependency must be declared in the package that imports it; otherwise the image or the function app misses it.
- **ACR remote builds use the classic builder:** no BuildKit features (`RUN --mount`, secret mounts) in Dockerfiles. The Dockerfile imports the entry point at build time to catch missing packages before deployment.
- **Tools reach the agent only through the toolbox** (`TOOLBOX_ENDPOINT`, published by `setup_platform.py connect-tools` after the MCP app deploys). `DIAGNOSTICS_MCP_URL` is for local development. Tool names arrive prefixed (`<server>___<tool>`).
- **Agent identities** exist only after `azd deploy`. The `grant-agent` hook gives the new identity its Cosmos DB role; it reads `AGENT_<SERVICE>_INSTANCE_IDENTITY_PRINCIPAL_ID`.
- **`azd ai agent run` needs `--start-command`** for our agents: the entry point is a module in a uv workspace, which azd can't detect. Don't set `startupCommand` in `azure.yaml` instead: azd also uses it to start the deployed container, which runs the Dockerfile's own command.
- **Model rate limits** (50k TPM by default) are easy to hit with several runs at once. The agent's chat client retries rate-limited calls; keep evaluation concurrency low.
- Preview features (hosted agents, toolboxes, azd agent extension) change often. Check current docs (Microsoft Learn) rather than memory before changing how they're configured, and verify role definition IDs instead of typing them from memory.
- **Before suggesting `azd provision`, validate:** `az bicep build --file infra/main.bicep`, then `az deployment sub what-if` with the azd environment's parameters. Call out any delete or replace in the what-if.

## Commits

- One logical change per commit, with all gates green. Imperative subject line that says what changed for a reader ("Add the platform API and csai episodes and feedback"), with a body only when the why isn't obvious.
- Commit only when asked, on a feature branch (not `main`), and don't push.
- Re-check the staged diff against the hard rules first.

## Where to start reading

- [`docs/specification.md`](docs/specification.md): what the platform must do and what's out of scope.
- [`docs/architecture.md`](docs/architecture.md): how the parts fit together.
- [`docs/foundry-findings.md`](docs/foundry-findings.md): limitations we hit and how we got past them.
- [`docs/adr/`](docs/adr/): decisions and their consequences. Read the relevant ADR before reversing one of them.
- [`docs/backlog.md`](docs/backlog.md): ideas for later, by theme. Start here when asked "what's next".
