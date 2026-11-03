# Foundry-native evaluation results

Status: four judges and all 13 code metrics verified; full-suite scale awaits budget,
3 November 2026.
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

**The first pass did not score all four judges.** The top-level service status says
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
submissions stopped at this blocker until the user approved a two-pass,
data-plane-only normalization and judging workaround. No hosted-agent deployment
was needed.

### Approved second pass: all four judges scored

Normalized all 40 saved tool calls without re-invoking the agent. JSON strings
become dictionaries; repeated complete objects are collapsed only when every
object is identical. Conflicting or malformed arguments fail offline before
submission. Report text, messages and tool results are unchanged. The original
agent-target run and its errors remain evidence.

The separate `eval-replay.yaml` run completed on those same five outputs:
all four built-in judges scored every row, with **zero evaluator execution errors**.
This proves the approved two-pass workflow, not single-pass compatibility.

### Usage after run 1

| Service usage entry | Tokens |
|---|---:|
| azure_ai_agent_target (five invocations) | 351,507 |
| gpt-5.4-mini-2026-03-17 (ten judge invocations) | 27,375 |
| azure_ai_evaluation (ten judge invocations) | 27,375 |
| First-pass conservative accounting | **406,257** |
| Normalized four-judge second pass | **221,936** |
| First code-grader startup rejection | **0** |
| Successful dense and four applicable-only code runs | **0** |
| Three unsuccessful SDK direct-target runs | **0 reported** |
| Two new applicable cases: agent target | **63,397** |
| Two new cases: named-model coherence usage | **4,919** |
| Two new cases: evaluation usage alias | **4,919** |
| Conservative cumulative accounting | **701,428 / 1,500,000** |

The two judge entries have identical counts and appear to alias the same usage.
Until deduplication is established, both count against the allowance.
Conservative remaining budget: **798,572 tokens**.
No original five agent invocations were repeated.

## Step 2: dense custom metrics

The code bundle reuses the actual local Pydantic report models and evaluator
functions, adapting only seed access to dataset reference IDs and causal notes.
Scores are computed in Foundry, not mirrored from precomputed values.
All **51 applicable offline comparisons** across dense and sparse metrics match
the local evaluators on the identical five Foundry outputs.

The first code run failed before scoring with zero tokens: the grader sandbox
disallows `globals()`, used by the initial Pydantic forward-annotation setup.
The revised bundle uses ordinary definition-order annotations, with no global
namespace introspection. The new evaluator version/run completed:
all **45 service-side dense scores** (nine metrics on five cases) match local
scoring at absolute tolerance `1e-12`, with zero execution errors and zero model
tokens.
The failed definition/run remain evidence; no quality-seeking rerun or agent
invocation was performed.

| Dense metric | Rows | Foundry mean | Maximum local difference |
|---|---:|---:|---:|
| hit_at_1 | 5 | 0.80 | 0 |
| hit_at_1_lenient | 5 | 0.80 | 0 |
| hit_at_3 | 5 | 0.80 | 0 |
| evidence_grounded | 5 | 0.80 | 0 |
| schema_valid | 5 | 0.80 | 0 |
| tool_coverage | 5 | 0.96 | 0 |
| knowledge_search_called | 5 | 1.00 | 0 |
| used_knowledge | 5 | 0.80 | 0 |
| calibration_score | 5 | 0.83348 | 0 |

These are prototype scores, not a release baseline. One report is invalid; its
applicable outcome scores are zero, as in the local reference.

## Step 3: applicable-case code evaluations

Separate static evaluations on the retained outputs completed:

| Metric | Applicable rows | Execution errors | Model tokens | Local parity |
|---|---:|---:|---:|---|
| decisive_evidence_recall | 4 | 0 | 0 | 4/4 |
| injection_resisted | 1 | 0 | 0 | 1/1 |
| ruled_out_correctly | 1 | 0 | 0 | 1/1 |
| data_quality_disclosed | 2 | 0 | 0 | 2/2 |

None of the original five cases applies to `data_quality_disclosed`. Two new,
unchanged suite cases cover sensor fault (SC-039) and data gap (SC-043).
Three attempts to combine an SDK agent target directly with this custom metric
failed with zero output rows and zero reported tokens:
`All examples failed due to invalid user input; please check the individual
sample outputs for details.` The output-items API returned no individual rows.
Changing row wrapping and matching the CLI's unpinned target selection did not
resolve it. An earlier malformed request was rejected before creating a run.
The exact underlying cause is unconfirmed; failed definitions, runs and receipts
are preserved. This does not establish a network failure or working single-pass
custom grading.

The proven CLI agent-target path then completed both new cases with coherence
judging, using 73,235 conservatively counted tokens. A separate static code run
scored `data_quality_disclosed` on these same saved outputs: both score 1.0,
both match locally, and the code run uses zero model tokens.
No original probe case was re-invoked. The unsupported SDK direct-target path
is not exposed as a working feature.

All **53 applicable service/local comparisons** match exactly:
45 dense, four decisive-recall, one injection, one ruled-out and two data-quality.
The [sanitized per-case evidence](../evals/rca/foundry/parity.json) contains only
case IDs, metric names, scores and differences. Raw outputs, service IDs and
portal links remain in private receipts.

## Step 4: budget decision before scaling

No 50-case run or repeat has been submitted. On the first five-case prototype,
agent generation used 351,507 tokens and the successful four-judge second pass
used 221,936 conservatively counted tokens. At that observed rate, 150 case
generations plus four-judge scoring would need about **17.2M additional tokens**,
before any extra startup-judge overhead. The two new cases cost less, so this is
a planning estimate, not a ceiling or a measured full-suite cost.
It cannot fit the remaining 798,572-token allowance. Increase the budget or
revise the scope before submission; do not start an intentionally partial run.

Full-suite repeats, combined judge/code evaluation and portal/API comparison
remain unproven. The approved two-pass workflow is proven; single-pass tool-aware
judging is not. No endpoint evaluators, infrastructure,
network, role or deployment changes were made.
The local harness, gate and thresholds are unchanged. Ruff check/format, Pyright
and 689 offline tests pass. No extra local-model evaluation was run: parity uses
the identical retained Foundry outputs, not freshly generated diagnoses.

The requested continuation differs from the original three-small-run spike:
step 2 adds nine dense code metrics (including `calibration_score = 1 - Brier`)
and per-case parity on identical outputs; step 3 runs decisive recall,
injection resistance, data-quality disclosure and ruled-out correctness as
separate applicable-case evaluations, without endpoints; step 4 scales to
50 cases and three measurements with portal/API comparison. None is claimed
complete merely because the first agent-target probe finished. Steps 1–3 now
have the evidence above; step 4 remains blocked on the budget decision.
