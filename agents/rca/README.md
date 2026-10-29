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

## Historical cases

When the toolbox supplies `azure_ai_search`, the instructions require a historical-case
search before concluding. Only relevant returned `HC-…` refs belong in the report; current
machine evidence still determines the diagnosis. Empty or irrelevant results are disclosed,
not cited to improve a score. Direct diagnostic MCP access has no search tool: the agent
continues its investigation and reports unavailable historical search in `missing_information`.
A failed search must be disclosed separately from an empty result.

The toolbox search entry has a diagnostic-specific `description`. Its payload follows the
[AzureAISearchToolboxTool schema](https://learn.microsoft.com/python/api/azure-ai-projects/azure.ai.projects.models.azureaisearchtoolboxtool?view=azure-python),
checked against Microsoft Learn and the installed SDK on 2026-10-29. This is the toolbox
entry's `description`, not the deprecated agent-level `AzureAISearchTool.description`.
[`ToolConfig.additional_search_text`](https://learn.microsoft.com/python/api/azure-ai-projects/azure.ai.projects.models.toolconfig?view=azure-python)
only supplements tool discovery and does not change `tools/list`.
The existing toolbox definition hash includes the description, so a future coordinated
publication will create a new version. Schema serialization alone does not establish that
the managed toolbox serves this description to an agent.

### A2 validation status

Offline tests exercise the real framework tool loop and episode capture with scripted
model turns for relevant, irrelevant, empty, failed and unavailable historical search. They verify
that supplied refs can be cited and irrelevant results can remain uncited; they do not
measure a model's adherence to the instructions.

The eval suite reports two separate informational metrics:

- `used_knowledge`: a report cites an `HC-…` ref, unchanged. It does not prove a search
  occurred, that the ref exists, or that the case is relevant.
- `knowledge_search_called`: an `azure_ai_search` call was recorded, including a
  toolbox-prefixed name. It flags attempts, not successful retrieval or relevant citations.
  Direct-MCP runs normally score zero.

**A2 remains incomplete pending live acceptance.** No new knowledge threshold is set;
every existing gate is unchanged. Before selecting a minimum, run repeated complete
`uv run csai eval rca --target local` suites in a serialized live slot against the same
model, data and toolbox. Retain per-case results, search calls/results and cited refs,
compare existing gates with the unchanged baseline, and inspect relevance rather than
forcing citations. A stable measured baseline must justify any future minimum. After an
approved coordinated deployment, inspect the hosted agent's discovered search description
and a fresh hosted investigation to confirm that metadata reaches the agent and relevant
citations resolve to returned cases. Neither live measurement nor feature deployment was
performed for the offline implementation.

## Deploy

`azd deploy rca-agent` exports the locked requirements, builds the image in the registry, creates a new hosted agent version and grants its identity the episode store role. Logs of a session: `azd ai agent monitor rca-agent -s <session-id>`.

## Tests

```bash
uv run pytest agents/rca
```

The golden-path test runs the agent offline: a scripted model calls the real diagnostics tool logic over the seed data, and the test checks that the report validates and that every cited ref appears in the tool results.
