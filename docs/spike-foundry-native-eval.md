# Spike: can Foundry run our evaluation?

Status: planned, 2026-11-03. Time box: a few working days. Backlog item [Q20](backlog.md#q-evaluation-you-can-trust), widened.

Today `csai eval` runs the agent locally, scores it with our own checks and is the only gate ([ADR 0009](adr/0009-evaluation-system-design.md)). Foundry only receives saved runs and adds model judges. This spike tests the opposite: Foundry calls the hosted agent, scores it with built-in judges **and** our own metrics as custom evaluators, compares runs and gates a release. The result is a decision, recorded as ADR 0010, and the plan for iteration 5.

## What waits for this spike

- **Judges-only publishing (Q16)** is stopped. In a Foundry-run evaluation we wouldn't publish local runs at all.
- **The three-repeat baseline** is postponed. It is measured after the decision, in the setup that wins. The retained 2026-11-02 50-case validation measurement is the local reference for comparisons.
- **Unchanged:** the local outcome gate (Q4) stays as the reference and fallback, and case promotion from consensus feedback (L9) goes ahead. Its cases become the Foundry dataset either way.

## What we need, and what the documentation says

Checked on Microsoft Learn on 2026-11-03. "Documented" means the docs describe it; it isn't proven in our network-injected project until the probe shows it.

| Need | Foundry capability | Documentation | Probe |
|---|---|---|---|
| Foundry calls our hosted agent | Agent target: the `azure_ai_target_completions` data source with an `azure_ai_agent` target. It works for hosted agents on the responses protocol with synchronous, non-streaming execution | Documented ([targets](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-targets)) | P1 |
| The target works in our network-injected project | The evaluation runtime calls the agent from the injected network | Not documented for agent targets; the [VNet evaluation page](https://learn.microsoft.com/azure/foundry/concepts/evaluation-virtual-network) covers runs in general | P1 |
| Evaluators see tool calls and citations | `{{sample.output_items}}` is the agent's structured output, including tool calls and results; `{{sample.output_text}}` is the text | Documented ([targets](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-targets), [agent evaluators](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/agent-evaluators)). Whether our toolbox MCP calls appear in it isn't | P2 |
| Tool judges work with our tools | Agent evaluators support MCP and function tools; Azure AI Search tool calls have limited support | Documented ([supported tools](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/agent-evaluators#supported-tools)). Our search goes through the MCP server, which should count as MCP | P2 |
| Our metrics as custom evaluators | Code evaluators: a `grade(sample, item)` function returning a float from 0 to 1, no network, 2 minutes per call. Prompt evaluators: an LLM rubric. Endpoint evaluators: our own HTTP endpoint | Documented, preview ([custom evaluators](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators)) | P3 |
| The answer key reaches the evaluator | Dataset fields arrive as `{{item.*}}`; a code evaluator reads `item` | Documented | P3 |
| "Doesn't apply" for some cases | Code evaluators return only a float. Endpoint evaluators can return `status: "skipped"` with a null score | Documented ([endpoint response schema](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators#endpoint-response-schema)) | P3 |
| Repeats per case | No repetition setting found for agent-target runs. Agent Framework's `evaluate_agent` has `num_repetitions`. Options: duplicate dataset rows with a repeat index, or run several times | Not documented | P4 |
| Run-to-run comparison with statistics | The portal compares runs against a baseline with t-tests and p-values; the API has comparison insights (average, standard deviation, sample count, p-value per metric) | Documented ([compare results](https://learn.microsoft.com/azure/foundry/how-to/evaluate-results#compare-the-evaluation-results)) | P4 |
| A gate in a pipeline | GitHub Action and Azure DevOps task: run the agent on a dataset with catalog evaluators, report confidence intervals and pairwise significance. Whether they fail a pipeline on a threshold isn't clear | Documented, preview ([GitHub Action](https://learn.microsoft.com/azure/foundry/how-to/evaluation-github-action), [Azure DevOps](https://learn.microsoft.com/azure/foundry/how-to/evaluation-azure-devops)) | P5 |
| Versioned cases and evaluators | Foundry datasets and evaluator versions; `azd ai agent eval generate / run / update` keeps `eval.yaml`, datasets and evaluators as local files registered as versions | Documented, preview ([azd evaluation](https://learn.microsoft.com/azure/foundry/observability/how-to/azure-developer-cli-evaluation)) | P5 |
| Episodes keep being captured | Our capture middleware runs inside the hosted agent, so Foundry's calls should be recorded like any other | Our design; not tested with Foundry as the caller | P1 |
| A hard check that fails on any single row | Pass rates per evaluator are documented; a pipeline that fails on one failed row isn't | Not documented | P5 |
| Cost and limits | Judge tokens; the deployment's 50 requests and 50k tokens per minute; judge scheduling is service-managed | Our measurement: 715k agent tokens for 50 cases; 763k judge tokens for 50 rows and 4 judges, 19m38s | All |

## Probes

One thin vertical slice, run against the deployed hosted agent. The five probes share three evaluation runs, so the agent is called 15 times in all. Each run needs the user's approval for its model traffic, and any Azure write needs its own.

**Metrics:** the same set as the earlier local runs and publication, so results stay comparable. Our checks cost no model tokens; only the judges do.

| Metric | Applies to | In Foundry |
|---|---|---|
| Task adherence, intent resolution, coherence, tool call accuracy | Every case | Built-in judges, as in the earlier publication |
| `hit_at_1`, `hit_at_1_lenient`, `hit_at_3`, `evidence_grounded`, `schema_valid`, `tool_coverage`, `knowledge_search_called`, `used_knowledge` | Every case | Code evaluators |
| `calibration` | Every case | Code evaluator, as `1 − Brier` so higher is better |
| `decisive_evidence_recall`, `ruled_out_correctly`, `injection_resisted`, `data_quality_disclosed` | Some cases | Endpoint evaluators that return "skipped" where the metric doesn't apply |

The gate stays as [ADR 0009](adr/0009-evaluation-system-design.md) decides: `hit_at_1_lenient`, `decisive_evidence_recall`, `evidence_grounded` and `injection_resisted` gate; the rest are reported.

**Dataset:** five cases from the current suite. Two original, and one each of injection, missing machine and a challenge case with decisive evidence. Each row carries the query and the answer-key fields our metrics need.

| Probe | What it does | Answers |
|---|---|---|
| **P1** | Run 1: an agent-target run on the five cases | Does Foundry reach the hosted agent in our network? Do the five episodes land in Cosmos DB? |
| **P2** | Run 1 includes the four judges; inspect `sample.output_items` | Are our toolbox MCP calls and results visible to evaluators? Does the tool judge accept them? |
| **P3** | Run 1 also includes all 13 of our metrics as custom evaluators (table above) | Can our metrics run in Foundry, including "doesn't apply"? |
| **P4** | Runs 2 and 3: the same dataset with all 13 custom evaluators and one judge (`task_adherence`). Compare the three runs in the portal and through the comparison API | Repeats, variance and significance without our harness |
| **P5** | Run 3 starts from `azd ai agent eval run` with `eval.yaml`. Look at the GitHub Action's inputs and outputs without running it | Versioned recipe and a pipeline gate. Can a pipeline fail when any applicable row fails injection resistance, as ADR 0009's hard check requires? |

**Estimated usage,** from the retained 50-case run (14,308 agent tokens per case) and its publication (3,816 tokens per judge call):

| Run | Agent | Judges | Total |
|---|---:|---:|---:|
| Run 1 (P1–P3): 5 cases, 4 judges | about 72k | about 76k | about 148k |
| Run 2 (P4): 5 cases, 1 judge | about 72k | about 19k | about 91k |
| Run 3 (P4, P5): 5 cases, 1 judge | about 72k | about 19k | about 91k |
| **All three** | | | **about 330k** |

These are averages, not ceilings. Retries, longer challenge cases and service overhead can add to them. Code and endpoint evaluators use no model tokens.

**Parity:** apply our local evaluators to Foundry's retained outputs from run 1 (each row's `output_text` and `output_items`), with the same answer keys and seed version. Compare per case, for all 13 metrics: each score and whether the metric applied. Running `csai eval` again would generate fresh diagnoses, so differences could come from the agent rather than the evaluators. Mapping Foundry's output items to our run records is a small adapter, written offline.

## Outcome and decision

The spike ends with:

1. The table above filled in: each need marked supported, partial or not, with the probe's evidence.
2. The probes' results, cost and duration, recorded in `docs/spike-foundry-native-eval-results.md`.
3. A recommendation, recorded as ADR 0010:
   - **Foundry-native** if the agent target works in our network, all four gate metrics run as custom evaluators (with "doesn't apply" handled and the injection hard check enforceable), per-case parity holds and comparison is usable. Iteration 5 rewrites the evaluation around it and retires most of `cs_platform.evals` and the publisher.
   - **Hybrid** if Foundry runs the agent and the judges but our metrics can't run there. Foundry runs and judges; our checks stay local or run as endpoint evaluators.
   - **Local** if the agent target can't run in our network. That is a finding worth publishing, and ADR 0009 stands.

## Rules for the spike

- Probes are experiments, not baselines. They don't change the gate, thresholds or cases.
- Synthetic data only; no environment specifics in tracked files.
- Preview features are checked against current docs at the time of each probe.
- Anything that needs a deployment change (an endpoint evaluator, a dedicated eval copy of the agent) is proposed first, with its cost.
