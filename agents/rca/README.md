# RCA agent

Diagnoses a machine incident from a field engineer's description. The agent gathers evidence with the diagnostics tools and returns an `RcaReport`: one to three ranked hypotheses, each with a failure-mode ID, root cause, confidence, cited evidence (`EV-…`, `LB-…`, `TS:<machine>:<signal>`, `EC-…`, `HC-…`) and recommended checks.

It's built entirely from platform parts (`cs-platform`): the spec and instructions declare the agent, `build_agent()` adds episode capture, and the tools come from the Foundry toolbox or a direct MCP server.

| File | Purpose |
|---|---|
| `src/rca_agent/agent.spec.yaml` | Name, version, description, instructions, tool sources, test cases |
| `src/rca_agent/instructions.md` | Role and pointer to the bundled skill |
| `skills/rca-investigation/SKILL.md` | Versioned investigation procedure and answer rules |
| `src/rca_agent/skill.py` | Bundled skill loading and episode version metadata |
| `src/rca_agent/report.py` | `RcaReport` schema (strict structured outputs) |
| `src/rca_agent/agent.py` | `create_agent()`: Azure-backed defaults, swappable for tests |
| `src/rca_agent/main.py` | Foundry hosted agent entry point (Responses protocol, port 8088) |
| `src/rca_agent/local.py` | `rca-local`: run against a local MCP server; also the report's terminal rendering |
| `Dockerfile` | Image for the hosted agent (build context: repository root) |

## Investigation skill

The procedure and answer rules live in `skills/rca-investigation/SKILL.md`, with Agent Skills front matter (`name`, `description`, `metadata.version`). Hatchling maps `skills` into `rca_agent/skills` in the wheel and includes it in source distributions; source runs read the same file from the checkout. The Dockerfile checks the installed skill at build time.

`create_agent()` reads the skill once, appends its body to the role instructions, and records its name and version as `Episode.skill` through an RCA-specific episode-store adapter, so every episode shows which procedure version produced it.

The whole procedure is always in context. That avoids an extra model-selected `load_skill` call and keeps every rule available on every turn, at the cost of context size. Progressive disclosure (Agent Framework's skills provider) hasn't been tried.

## Historical cases

When the toolbox supplies `azure_ai_search`, the instructions require a historical-case search before concluding. Only relevant returned `HC-…` refs belong in the report; current machine evidence still decides the diagnosis. Empty, irrelevant or failed searches are disclosed rather than cited. A direct MCP server has no search tool: the agent continues and reports the unavailable search in `missing_information`.

The toolbox's search entry has a diagnostic-specific `description` (the [AzureAISearchToolboxTool](https://learn.microsoft.com/python/api/azure-ai-projects/azure.ai.projects.models.azureaisearchtoolboxtool?view=azure-python) field, set in `scripts/setup_platform.py`).

## Run locally

With a deployed environment, run the agent on your machine against the deployed models and toolbox:

```bash
azd ai agent run                                                              # terminal 1
azd ai agent invoke --local "M-0001: overlay getting worse, stage temperature alarm this morning"  # terminal 2
```

To work on tools too, run the MCP server on your machine and point `rca-local` at it:

```bash
# terminal 1
cd services/diagnostics-mcp && uv run func start

# terminal 2 (from the repository root)
cp agents/rca/.env.sample .env        # Foundry endpoint and deployment; DIAGNOSTICS_MCP_URL
az login
uv run rca-local "M-0001: overlay getting worse, stage temperature alarm this morning"
```

The output shows the ranked hypotheses with their evidence, then the episode: tool calls with durations, token usage and trace ID. Episodes stay in memory locally; Cosmos DB is private ([ADR 0003](../../docs/adr/0003-private-data-stores.md)). Set `APPLICATIONINSIGHTS_CONNECTION_STRING` to export traces ([tracing](../../docs/tracing.md)).

## Deploy

`azd deploy rca-agent` exports the locked requirements, builds the image in the registry, creates a new hosted agent version and grants its identity the episode store role. Follow its logs with `azd ai agent monitor rca-agent --follow`.

## Tests

```bash
uv run pytest agents/rca
```

The golden-path test runs the agent offline: a scripted model calls the real diagnostics tool logic over the seed data, and the test checks that the report validates and that every cited ref appears in the tool results.
