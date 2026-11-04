# Foundry-native evaluation results

Status: **closed on 4 November 2026.** The decision is
[ADR 0010](adr/0010-evaluation-runs-in-foundry.md); the remaining work is in the
[backlog](backlog.md#q-evaluation-you-can-trust) as iteration 5's scope.
Limitations found here are also in [Foundry findings](foundry-findings.md).
The spike used 701,428 of the approved 1.5M model tokens and made no
infrastructure, network, role or deployment changes.

## Outcome

The [spike plan's](spike-foundry-native-eval.md) capability table, answered:

| Need | Result | Evidence |
|---|---|---|
| Foundry calls our hosted agent | **Supported** | Five agent-target invocations, then two more cases ([step 1](#step-1-hosted-agent-and-four-judges)) |
| The target works in our network-injected project | **Supported** | Same runs; no network change needed |
| Evaluators see tool calls and results | **Supported** | `sample.output_items` holds the toolbox calls with results; use `sample.output_text` for the answer, since `sample.output` is dropped for size |
| Tool judges work with our tools | **Partial** | Only after converting the arguments to dictionaries in a second run; a hosting adapter bug also duplicates them ([diagnosis](#proven-snapshot-defect-not-repeated-tool-execution)) |
| Our metrics as custom evaluators | **Supported** | All 13 as code evaluators: 53/53 exact matches on the probe outputs and 532/532 on the retained 50-case run |
| The answer key reaches the evaluator | **Supported** | Dataset fields read from `item` |
| "Doesn't apply" for some cases | **Partial** | One evaluation per sparse metric over its applicable cases; endpoint evaluators (which can skip) not tried |
| Agent and our metrics in one run | **Not working** | Three SDK attempts failed with zero rows and a generic invalid-input error |
| Repeats per case | Not tested | No repetition setting; duplicate rows or several runs |
| Run comparison with statistics | Not tested | |
| A gate in a pipeline, including a hard check | Not tested | Pass counts per evaluator only; the gate's means and hard check have to be computed from run results |
| Versioned cases and evaluators | **Partial** | Evaluator versions work. Dataset upload hit the private storage boundary; the Files API worked. `azd ai eval` can't pin the agent version |
| Episodes captured with Foundry as caller | **Supported** | Hosted episodes retrieved for all five probe cases |
| Cost | **Measured** | About 25k agent tokens and 22k judge tokens per case; reported usage is inflated by the adapter bug and duplicate judge entries |

Against the plan's decision rules this is between Foundry-native and hybrid:
Foundry calls the agent, runs the judges and computes all our metrics with exact
parity, but in two steps, with sparse metrics split into separate evaluations,
and without proven repeats, comparison or a pipeline gate.

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

## Step 4: fresh agent runs remain on hold

No fresh 50-case agent-target run or repeat has been submitted. The initial
**17.2M-token** three-run estimate summed inflated protocol usage and both judge
usage aliases. The read-only diagnosis below supersedes that estimate, not the
1.5M allowance or the requirement for approval before any new target/judge run.

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
have the evidence above; fresh step-4 measurements remain on hold.

## Retained local outputs: full 50-case scoreboard

The immutable 2 November single-repeat measurement supplies **18 original and
32 challenge cases**, with no feedback cases and no plumbing exclusions.
Export preserved its report text, answer keys and actual tool traces. Original
scores were kept separately for comparison, never supplied as grader inputs.
SHA256 checks of the manifest, events, episodes and completion certificate are
unchanged after export and scoring.

Five runs named **RCA retained local outputs 2026-11-02 - [metric group]**
completed in Foundry: nine dense metrics on all 50 rows, then four separate
applicable-only evaluations. They are static code-only evaluations of local
answers, **not hosted-agent generations, fresh measurements or a three-repeat
baseline**. All runs are visible in the portal; their IDs, links and uploaded
file receipts remain private.

Direct `datasets.upload_file` failed with `AuthorizationFailure` at the private
storage boundary. The approved project Files API accepted uploaded JSONL
evaluation datasets (`purpose=evals`, `source.type=file_id`). These are project
files, not newly registered DatasetVersion assets. No storage, network or role
configuration changed.

| Metric | Applicable rows | Foundry mean | Current-local parity |
|---|---:|---:|---:|
| hit_at_1 | 50 | 0.78 | 50/50 |
| hit_at_1_lenient | 50 | 0.78 | 50/50 |
| hit_at_3 | 50 | 0.90 | 50/50 |
| evidence_grounded | 50 | 0.92 | 50/50 |
| schema_valid | 50 | 0.92 | 50/50 |
| tool_coverage | 50 | 0.896 | 50/50 |
| knowledge_search_called | 50 | 0.88 | 50/50 |
| used_knowledge | 50 | 0.74 | 50/50 |
| calibration_score (1 - Brier) | 50 | 0.857294 | 50/50 |
| decisive_evidence_recall | 46 | 0.75 | 46/46 |
| injection_resisted | 4 | 1.00 | 4/4 |
| data_quality_disclosed | 8 | 1.00 | 8/8 |
| ruled_out_correctly | 24 | 0.916667 | 24/24 |

**532/532 exact service/current-local comparisons**, maximum difference zero;
zero evaluator errors and **zero model tokens**. The aggregate local reference
gate passes at **0.78 / 0.75 / 0.92**, with injection **4/4**, against provisional
floors 0.70 / 0.65 / 0.85 and the injection hard check. Foundry's individual row
pass thresholds are not this aggregate gate.

Comparison with the frozen historical scores is **530/532**. SC-031 and SC-033
originally scored grounding 1.0; ADR 0009's invalid-report rule makes both 0.0.
The historical grounding mean is therefore 0.96 versus current-rule 0.92.
These are the two already-known rule changes, not new service/local mismatches.
Four invalid reports remain failed case-runs rather than plumbing exclusions.
No threshold change is proposed. The
[per-case CSV](../evals/rca/foundry/retained-parity.csv) preserves both comparisons.

## Read-only cost and tool-argument diagnosis

Retrieved the five original stored Responses and their exact, untruncated hosted
episodes. Compared those with matching cases in the retained local journal.
This did not generate any new responses.

| Case | Local tools | Hosted tools | Local tokens | Hosted episode tokens | Responses-reported tokens |
|---|---:|---:|---:|---:|---:|
| SC-001 | 8 | 9 | 14,921 | 18,268 | 36,550 |
| SC-002 | 8 | 8 | 24,520 | 35,972 | 117,124 |
| SC-019 | 7 | 8 | 10,185 | 20,144 | 47,558 |
| SC-031 | 2 | 7 | 5,610 | 29,561 | 86,768 |
| SC-035 | 8 | 8 | 21,394 | 22,969 | 63,507 |
| Total | **33** | **40** | **76,630** | **126,914** | **351,507** |

The matched local mean is **15,326**, not a universal 14k cost. Hosted captured
usage averages **25,383**, about **1.66x** local, while the protocol reports
**70,301**, about **2.77x** the captured hosted usage. This is primarily an
accounting defect, with a smaller real investigation/context difference.
It is not evidence that the agent actually spent 70k tokens per case.

### Proven snapshot defect, not repeated tool execution

All **40/40** serialized calls contain two identical complete argument objects.
After lossless normalization each matches exactly one captured tool execution,
including its name and arguments. There are **zero repeated identical
name/argument executions**. Repeated lookup and telemetry tool names address
different error codes or signals.

The deployed image's SDK source was read directly from its immutable registry
layers, without running a container. Its hosting adapter, core tool loop and
Responses client source match the locally inspected files byte-for-byte:
`agent-framework-foundry-hosting` 1.0.0b261015, core 1.22.0 and
`agent-framework-openai` 1.17.0.

The OpenAI client emits argument deltas with `merge_mode="append"`, followed by
the complete argument snapshot with `merge_mode="replace"`. The core tool loop
also projects cumulative usage with `merge_mode="replace"`.
Hosting `_OutputItemTracker.handle` ignores that distinction for calls and usage:
it appends every argument string and adds every usage snapshot. The final
framework response used by episode capture correctly honors replacement.

The [offline reproduction](../evals/rca/foundry/stream_repro.py) feeds identical
updates into the real hosting tracker and final-response aggregator:

| Input updates | Hosting result | Correct final-response result |
|---|---|---|
| Arguments delta, then identical replacement snapshot | Two concatenated JSON objects | One JSON object |
| Usage snapshots 100/10, then 250/25 input/output | 350/35 (385 total) | 250/25 (275 total) |

This reproduces both observed defects with **zero model calls**, without
patching site-packages or changing the deployed agent.

### Search, instructions, model and real trajectory differences

`azure_ai_search` is already present in the retained local tool definitions and
four of the five local traces. It is not a newly added Foundry evaluation tool.
Hosted invoked search on all five cases; SC-019 accounts for the extra search.
SC-001 adds one telemetry window. SC-031 adds five tools: the hosted missing-ID
trajectory explores context, errors, logbook and three code lookups, while the
local trajectory uses only context and search.

The deployed instruction file, full investigation skill, agent construction and
entry point are byte-identical to the retained revision. Both use
`gpt-5.4-mini`; read-only deployment metadata and token-meter dimensions identify
model version `2026-03-17`. No changed model or instruction body explains the
five-case gap. Hosted runs stream internally even when their Responses caller
does not; local runs are non-streaming. Five saved trajectories cannot establish
how much of the remaining 1.66x difference is sampling versus streaming/context
behavior. No speculative instruction or search-tool removal was made.

### Judge aliases and independent model meters

The named-model and `azure_ai_evaluation` usage entries have identical token and
invocation counts. Read-only deployment meters provide independent evidence
against treating them as two separately charged judge batches:

| UTC window, 3 November | Metered prompt | Metered generated | Interpretation |
|---|---:|---:|---|
| 20:40-21:18, original target run | 147,099 | 7,278 | Agent plus initial judges; 154,377 total, not the 406,257 summed service entries |
| 21:18-21:24, static four-judge replay | 100,305 | 4,092 | One judge batch; not the 221,936 summed aliases |

The first window agrees closely with captured agent usage plus one named judge
entry: 154,289 versus 154,377, an **88-token** residual. The replay's named entry
is 110,968 versus metered 104,397, a **6,571-token** residual. Its request meter
shows 21 HTTP-200 requests and seven HTTP-429 requests, not two sets of 20
successful judge invocations. These are deployment-level operational meters,
not an invoice or per-request billing export; the residuals are not explained.
The evidence supports duplicate reporting aliases, not double model charging.
Do not sum a named-model breakdown and its evaluation roll-up for cost planning.

The allowance ledger remains conservatively **701,428 / 1,500,000**, with
**798,572** remaining. This work adds **zero** model tokens. No budget is
automatically reclaimed from these findings.

### Exact proposed fix and deployment implications

Fix the hosting adapter, not the local evaluators:

1. Honor `merge_mode` for function/MCP arguments. Append true deltas; replace
   accumulated state for snapshots. When a snapshot extends the already emitted
   prefix, emit only the new suffix; a non-prefix replacement must not be
   serialized as an append. The completed item must contain exactly the final
   arguments, or fail explicitly if the stream cannot represent the correction.
2. Replace cumulative usage snapshots instead of summing them. At completion,
   use the finalized `AgentResponse.usage_details` as authoritative for both
   stored and streamed Responses, matching episode capture.
3. Keep valid Responses function-call arguments as JSON **strings**, as the
   protocol requires. The built-in judges require dictionaries: retain the
   approved second-pass dictionary conversion until Foundry's target-to-judge
   bridge supports this correctly. Fixing duplicate strings alone does not
   prove single-pass judging works.
4. Report named judge model usage once, with the aggregate alias labeled rather
   than added. Preserve raw counters and reconcile against model meters.

Prefer a verified fixed hosting SDK version; otherwise use a small, tested
hosting-boundary adapter implementing the above semantics. Neither has been
installed or deployed by this PR. Regression tests must cover fragmented deltas,
replacement snapshots, multiple tool rounds/calls, final usage agreement and
unrepresentable replacements before selecting a deployable fix.

Deploying the agent-side correction requires changing/pinning the owning runtime
dependency or adapter, regenerating the ignored lock export, rebuilding the
agent image and deploying a new hosted-agent version. It requires **separate
deployment approval**, but no identified infrastructure, network or role change.
The existing dataset-side argument normalizer needs no agent deployment.

This fixes reported cost and corrupted arguments; it does **not** promise lower
actual model consumption. For planning only, 25,383 captured agent tokens plus
22,194 unaliased replay judge tokens per case implies roughly **2.4M per 50-case
measurement, 7.1M for three**, before retries and cohort variance. Even that
corrected estimate exceeds the current allowance. Further real-cost tuning
requires evidence after the approved runtime correction, not deleting search or
guessing at instruction changes.

No new judges, agent-target runs, deployments or Azure configuration writes
were performed. No 50-case judging or model-budget approval request is included.
