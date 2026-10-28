# RCA agent

Diagnoses a machine incident from a field engineer's description. The agent gathers evidence with the diagnostics tools and returns an `RcaReport`: one to three ranked hypotheses, each with a failure-mode ID, root cause, confidence, cited evidence (`EV-…`, `LB-…`, `TS:<machine>:<signal>`, `EC-…`, `HC-…`) and recommended checks.

It's built entirely from platform parts (`cs-platform`): the spec and instructions declare the agent, `build_agent()` adds episode capture, and the tools come from the Foundry toolbox or a direct MCP server.

| File | Purpose |
|---|---|
| `src/rca_agent/agent.spec.yaml` | Name, version, description, instructions, tool sources, eval suite |
| `src/rca_agent/instructions.md` | Investigation procedure and answer rules |
| `src/rca_agent/report.py` | `RcaReport` schema (strict structured outputs) |
| `src/rca_agent/agent.py` | `create_agent()`: Azure-backed defaults, swappable for tests |
| `src/rca_agent/main.py` | Foundry hosted agent entry point (Responses protocol, port 8088) |
| `src/rca_agent/local.py` | `rca-local`: run on your machine against the toolbox or a local MCP server |
| `Dockerfile` | Image for the hosted agent (build context: repository root) |

## Run locally

With a deployed environment, the simplest path is `csai`, which reads its settings from azd and uses the deployed toolbox:

```bash
uv run csai diagnose "M-0001: overlay getting worse, stage temperature alarm this morning" --target local
uv run csai eval rca --target local
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

The output shows the ranked hypotheses with their evidence, then the episode: tool calls with durations, token usage and trace ID. Episodes stay in memory locally; Cosmos DB is private (ADR 0003).

## Deploy

`azd deploy rca-agent` exports the locked requirements, builds the image in the registry, creates a new hosted agent version and grants its identity the episode store role. Logs of a session: `azd ai agent monitor rca-agent -s <session-id>`.

## Tests

```bash
uv run pytest agents/rca
```

The golden-path test runs the agent offline: a scripted model calls the real diagnostics tool logic over the seed data, and the test checks that the report validates and that every cited ref appears in the tool results.
