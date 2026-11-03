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
| Cost and limits | Judge tokens; the deployment's 50 requests and 50k tokens per minute; judge scheduling is service-managed | Our measurement: 763k judge tokens for 50 rows and 4 judges, 19m38s | All |

## Probes

One thin vertical slice, run against the deployed hosted agent. Each probe needs the user's approval for its model traffic and any Azure writes. Expected total: well under 200k tokens.

**Dataset:** five cases from the current suite. Two original, and one each of injection, missing machine and a challenge case with decisive evidence. Each row carries the query and the answer-key fields our metrics need.

| Probe | What it does | Answers |
|---|---|---|
| **P1** | Agent-target run on the five cases, judges only (task adherence, intent resolution) | Does Foundry reach the hosted agent in our network? Do the five episodes land in Cosmos DB? |
| **P2** | Same run, inspect `sample.output_items`; add `tool_call_accuracy` | Are our toolbox MCP calls and results visible to evaluators? Does the tool judge accept them? |
| **P3** | Add three custom evaluators: correct cause (code, from `output_text` and the answer key), citations real (code, from `output_items`), decisive evidence as an endpoint evaluator that returns "skipped" where it doesn't apply | Can our gate metrics run in Foundry, including "doesn't apply"? |
| **P4** | Three runs of the same dataset, or one run with each row three times; compare runs in the portal and through the comparison API | Repeats, variance and significance without our harness |
| **P5** | The same evaluation from `azd ai agent eval run` with `eval.yaml`, and a dry look at the GitHub Action's inputs and outputs | Versioned recipe and a pipeline gate |

Then compare the five cases with `csai eval` on the same agent version: do Foundry's custom metrics give the same scores as ours?

## Outcome and decision

The spike ends with:

1. The table above filled in: each need marked supported, partial or not, with the probe's evidence.
2. The probes' results, cost and duration, recorded in `docs/spike-foundry-native-eval-results.md`.
3. A recommendation, recorded as ADR 0010:
   - **Foundry-native** if the agent target works in our network, our gate metrics run as custom evaluators (with "doesn't apply" handled) and comparison is usable. Iteration 5 rewrites the evaluation around it and retires most of `cs_platform.evals` and the publisher.
   - **Hybrid** if Foundry runs the agent and the judges but our metrics can't run there. Foundry runs and judges; our checks stay local or run as endpoint evaluators.
   - **Local** if the agent target can't run in our network. That is a finding worth publishing, and ADR 0009 stands.

## Rules for the spike

- Probes are experiments, not baselines. They don't change the gate, thresholds or cases.
- Synthetic data only; no environment specifics in tracked files.
- Preview features are checked against current docs at the time of each probe.
- Anything that needs a deployment change (an endpoint evaluator, a dedicated eval copy of the agent) is proposed first, with its cost.
