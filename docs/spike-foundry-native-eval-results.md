# Foundry-native evaluation results

Status: blocked on tool-call argument serialization, 3 November 2026.
The [spike](spike-foundry-native-eval.md) is now an execution task.
Model usage is authorized up to 1.5M tokens cumulatively; project evaluation
data-plane writes are approved. Infrastructure, network, roles and deployments
remain unchanged.

## Step 1: hosted agent and four judges

The old `azd ai agent eval` flow has been removed. The installed replacement,
`azure.ai.evaluations` 1.0.0-beta.2, supports `azd ai eval`.
The recipe is `evals/rca/foundry/eval.yaml`; environment-specific rendering
and service receipts stay outside tracked files.

Submitted an `azure_ai_target_completions` run with an `azure_ai_agent` target.
The saved service request confirms a user-message template (responses protocol),
not a completed-response publication. The CLI currently rejects a target
`version` field, so it selects the deployed agent by name.

Five existing cases: SC-001, SC-002, SC-019 (overlapping),
SC-031 (missing machine), SC-035 (injection).
Judges: task adherence, intent resolution, coherence and tool call accuracy.
Their mappings use generated `sample.output_text` / `sample.output_items`,
with retained tool schemas supplied as dataset context.

**Reachability works.** Foundry completed all five agent invocations in the
network-injected project. Generated tool calls and report text are retained.
The run is visible in the portal; its ID, portal URL and raw results remain in
private receipts, not tracked environment-specific configuration.

**The four-judge step is not complete.** The top-level service status says
`completed`, five passed and zero errored, but per-criterion inspection finds:

| Judge | Scored rows | Execution errors |
|---|---:|---:|
| intent_resolution | 5 | 0 |
| coherence | 5 | 0 |
| task_adherence | 0 | 5 |
| tool_call_accuracy | 0 | 5 |

Both failed judges report `FAILED_EXECUTION`:

> The 'arguments' field must be a dictionary in tool_call content items.

`datasource_item["sample.output_items"]` contains the tool calls, but their
`arguments` are strings. Some contain concatenated JSON objects, for example
`{"machine_id":"M-0001"}{"machine_id":"M-0001"}`. This is not a network failure.
Simply parsing a single JSON value would not fix every retained call.
The actual generated report is in
`datasource_item["sample.output_text"]`; `sample.output` is empty with
`_raisvc_content_omission` recording `size_limit`.
Do not infer missing agent output or successful judging from the summary alone.

No mapping workaround was substituted that hides the tool calls. Further
submissions stopped at this blocker. Resolving the argument serialization needs
a decision on the hosted response bridge or evaluation-service normalization;
any hosted-agent deployment remains separately approval-gated.

### Usage after run 1

| Service usage entry | Tokens |
|---|---:|
| azure_ai_agent_target (five invocations) | 351,507 |
| gpt-5.4-mini-2026-03-17 (ten judge invocations) | 27,375 |
| azure_ai_evaluation (ten judge invocations) | 27,375 |
| Conservative cumulative accounting | **406,257 / 1,500,000** |

The two judge entries have identical counts and appear to alias the same usage.
Until deduplication is established, both count against the allowance.
Conservative remaining budget: **1,093,743 tokens**.
No new run was submitted after this result.

## Remaining steps

Steps 2–4 have not run. Dense-metric parity, sparse per-metric evaluations,
full-suite repeats and comparison remain unproven. No custom evaluator versions,
endpoint evaluators, infrastructure, network, role or deployment changes were made.
The local harness, gate and thresholds are unchanged. The five-case run already
uses substantially more agent tokens per case than the historical estimate;
full-suite repetitions cannot be presumed to fit the remaining allowance.

The requested continuation differs from the original three-small-run spike:
step 2 adds nine dense code metrics (including `calibration_score = 1 - Brier`)
and per-case parity on identical outputs; step 3 runs decisive recall,
injection resistance, data-quality disclosure and ruled-out correctness as
separate applicable-case evaluations, without endpoints; step 4 scales to
50 cases and three measurements with portal/API comparison. None is claimed
complete by this first agent-target probe.
