# RCA agent

Diagnoses a machine incident from a field engineer's description. The agent gathers evidence with the diagnostics tools and returns an `RcaReport`: one to three ranked hypotheses, each with a failure-mode ID, root cause, confidence, cited evidence (`EV-…`, `LB-…`, `TS:<machine>:<signal>`, `EC-…`, `HC-…`) and recommended checks.

It's built entirely from platform parts (`cs-platform`): the spec and instructions declare the agent, `build_agent()` adds episode capture, and the tools come from the Foundry toolbox or a direct MCP server.

| File | Purpose |
|---|---|
| `src/rca_agent/agent.spec.yaml` | Name, version, description, instructions, tool sources, eval suite |
| `src/rca_agent/instructions.md` | Role and pointer to the bundled skill |
| `skills/rca-investigation/SKILL.md` | Versioned investigation procedure and answer rules |
| `src/rca_agent/skill.py` | Bundled skill loading and episode version metadata |
| `src/rca_agent/report.py` | `RcaReport` schema (strict structured outputs) |
| `src/rca_agent/agent.py` | `create_agent()`: Azure-backed defaults, swappable for tests |
| `src/rca_agent/main.py` | Foundry hosted agent entry point (Responses protocol, port 8088) |
| `src/rca_agent/local.py` | `rca-local`: run on your machine against the toolbox or a local MCP server |
| `Dockerfile` | Image for the hosted agent (build context: repository root) |

## Versioned investigation skill (L1)

The procedure and answer rules live in `skills/rca-investigation/SKILL.md`, with
Agent Skills front matter (`name`, `description`, `metadata.version`). The optimizer's
source layout remains separate from `src`; Hatchling maps `skills` into
`rca_agent/skills` in the wheel and includes it in source distributions. Source runs
read the same file from the checkout. The Dockerfile checks the installed skill at build time.

`create_agent()` reads the skill once, appends its body once to the role instructions,
and records its name and version as optional `Episode.skill` metadata through an
RCA-local episode-store adapter. Both injected and default stores receive the metadata.
Older episodes and agents without a skill retain `skill=None`. No shared factory,
capture middleware or agent-spec changes are needed.

**Always-in-context remains the default.** It avoids an extra
model-selected `load_skill` call and keeps every procedure rule available on every
turn, at the cost of including the full procedure in context. Progressive disclosure
is not implemented or measured here; no equivalence claim is made. The procedure and
answer-rule text is unchanged, but offline scripted turns cannot establish equivalent
model behavior.

Offline tests cover the real tool loop, context inclusion exactly once in the built agent,
episode metadata and legacy compatibility, and loading from an installed wheel rebuilt
from its source distribution.

The frozen `59d273d` bundled-skill candidate passed the unchanged gates on the original
18 cases with three serialized repeats: all 54 final episodes succeeded, tool coverage
was 0.9333 and knowledge citations were 0.7037 against the unchanged 0.70 minimum.
The retained pre-skill baseline still fails that knowledge gate at 0.4444. A first
cancelled attempt's 25 rounded console observations remain separate and inconclusive;
the sole complete technical recovery does not pool them into its results.

All/train/test paired comparisons have no entirely negative difference interval on
the common metrics, but train/test knowledge intervals include zero. These observations
do not establish causal improvement, formal equivalence or noninferiority.
One approved hosted diagnosis verified exact response-to-episode correlation, raw
skill/source metadata and complete tool/output capture from the deployed revision.
Reading the new metadata also required a coordinated platform API deployment.
See [L1 evidence](../../docs/iteration-3/l1.md) for measurements and limitations.
Subsequent main integration passed 374 offline tests. The live measurements above
apply to frozen `59d273d`, not a new live validation of the integrated challenge suite.

The deployed path remains the bundled copy. Progressive disclosure was not measured
or selected. Current Agent Framework skill documentation was checked, but a
Foundry-native consumption path was not verified and no skill resource was published.
No unsupported publishing configuration or remote skill API is assumed.

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

Both local entry points configure telemetry. Set `APPLICATIONINSIGHTS_CONNECTION_STRING`
to export it; without that setting, a valid local trace ID is not queryable in Azure.
See [trace continuity](../../docs/tracing.md) for sampling and outstanding hosted verification.

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

The eval suite reports two separate knowledge metrics:

- `used_knowledge`: a report cites an `HC-…` ref, unchanged. It does not prove a search
  occurred, that the ref exists, or that the case is relevant. Its measured mean
  regression gate is 0.70 for toolbox-backed evaluation.
- `knowledge_search_called`: an `azure_ai_search` call was recorded, including a
  toolbox-prefixed name. It flags attempts, not successful retrieval or relevant citations.
  It remains informational. Direct-MCP runs normally score zero on both metrics;
  they can diagnose without search but cannot satisfy the toolbox knowledge gate.

On 2026-10-29, after the approved combined feature deployment, three sequential complete
18-case local suites ran at concurrency 1 against the same snapshot
(`4afdaa4d2f923c2ac0d66aea9779a1091f13bbbb`), model, seed data and deployed toolbox.
The driver reused the CLI's evaluation path and saved actual in-memory episodes, complete
tool results, reports, timestamps and per-case scores. No case errored; all attempts were
first attempts. Accuracy (`hit_at_1`, `hit_at_3`), schema validity and evidence grounding
were 1.0 in all three suites.

| Repeat | Search calls / cases | Reports citing history / cases | Distinct diagnostic calls / opportunities | Replayed coverage |
|---|---|---|---|---|
| 1 | 16 / 18 | 16 / 18 | 82 / 90 | 0.9111111111111111 |
| 2 | 16 / 18 | 16 / 18 | 83 / 90 | 0.9222222222222223 |
| 3 | 15 / 18 | 14 / 18 | 81 / 90 | 0.9 |

The original third suite **failed** with `tool_coverage: 0.90 < 0.90`: naive float
summation produced `0.8999999999999999` for the exact count `81 / 90`. Its original
results and failed summary were retained, not rewritten. Replaying all 54 unchanged
case scores with the shared harness's `statistics.mean` fix passes every existing gate.
The fix changes arithmetic only: no scores, thresholds or comparisons were relaxed, and
regression tests check both the exact boundary and the next representable float below it.
No new model runs were needed for this replay.

The citation audit found no unknown or unreturned `HC-` refs. All 46 reports citing
history had returned, existing historical cases; 45 also cited a case confirmed for
the expected primary failure mode. The other report cited a plausible secondary mode.
Existence is not relevance: five citations were attached to a different or `unknown`
hypothesis; two explicitly described the historical pattern as not matching this incident
(repeat 2, `SC-003` and `SC-011`). Those should not be treated as positive grounding.
They were not required to achieve the score, and the instructions must not encourage
their inclusion.

Actual toolbox discovery after deployment returned all six tools, including
`azure_ai_search` with a description exactly matching the updated source. The existing
hosted correlation check also searched and cited returned `HC-0007` for the matching
`FM-07` hypothesis; its search result was untruncated. No additional hosted model call
was made for this audit. Nevertheless,
seven investigations skipped search and incorrectly disclosed it as unavailable:
repeat 1 `SC-009`, `SC-014`; repeat 2 `SC-004`, `SC-007`; repeat 3 `SC-001`, `SC-014`,
`SC-018`. These are recorded instruction-compliance failures, not successful fallback
tests. Repeat 3 `SC-010` searched and acknowledged a matching case but did not cite it.

Removing all five different/unknown-hypothesis citations leaves the measured citation
counts unchanged at 16/18, 16/18 and 14/18: every counted report still cites at least one
returned case confirmed for a stated hypothesis. Thus questionable secondary citations
do not inflate this binary baseline. Across these three repeated, fixed-configuration
runs, citation use stayed within a two-case range and every existing gate passed after
the arithmetic correction. This supports a conservative **citation regression** minimum,
not a 100% instruction-compliance claim.

The new `used_knowledge` minimum is **0.70**, requiring 13 of these 18 reports to cite
history. That allows one fewer report than the measured worst run (14/18), while a drop
to 12/18 fails. All three retained suites pass this additional gate without changing
case scores, instructions or any existing threshold. This small baseline is not a
statistical guarantee for other models, toolboxes or data; behavior changes need another
serialized repeated evaluation and relevance review.

**A2's instruction, metadata and measured-gate scope is verified.** Search omissions and
irrelevant secondary citations remain explicit model-behavior limitations; no deterministic
required-tool middleware was added, and no citation is required for irrelevant results.
Private raw results, episodes, discovery metadata and arithmetic/gate replays remain
outside version control.

## Deploy

`azd deploy rca-agent` exports the locked requirements, builds the image in the registry, creates a new hosted agent version and grants its identity the episode store role. Logs of a session: `azd ai agent monitor rca-agent -s <session-id>`.

## Tests

```bash
uv run pytest agents/rca
```

The golden-path test runs the agent offline: a scripted model calls the real diagnostics tool logic over the seed data, and the test checks that the report validates and that every cited ref appears in the tool results.
