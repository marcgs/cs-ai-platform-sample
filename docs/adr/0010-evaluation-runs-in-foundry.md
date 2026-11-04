# ADR 0010: Evaluation runs in Foundry

- **Status:** Proposed
- **Date:** 2026-11-04
- **Supersedes:** the parts of [ADR 0009](0009-evaluation-system-design.md) that say where evaluation runs. Its gate metrics and rules stay.

## Context

[ADR 0009](0009-evaluation-system-design.md) made `csai eval` the only gate: our harness runs the agent locally, scores it with code checks against an answer key, and Foundry only shows model judges on saved runs. That works, but it's our own evaluation system with Foundry attached. This sample exists to show what Foundry and Agent Framework give a team, so we ran a [spike](../spike-foundry-native-eval.md) on letting Foundry run the evaluation.

The [results](../spike-foundry-native-eval-results.md#outcome):

- **Proven:** Foundry calls the hosted agent inside the network-injected project. All 13 of our metrics run as Foundry code evaluators and give exactly the same scores as our local code (532 of 532 on the retained 50-case run). The four built-in judges score every row.
- **Proven only in two steps:** Foundry calls the agent in one run, then scores the saved outputs in a second run. The tool judges need the second step because of a bug in the hosting adapter and a format mismatch between the Responses protocol and the judges. Combining the agent call with our code evaluators in one run failed three times with a generic error.
- **Not proven:** repeats, run comparison and a pipeline gate.
- **Gaps:** code evaluators can't return "doesn't apply", so each sparse metric needs its own evaluation. The portal shows pass counts, not the means our gate uses.

We also drifted from a principle we started with. We built our own evaluation harness first, because Foundry evaluation didn't work in our private network at the time, and then kept measuring Foundry against it. That produced a lot of machinery (parity checks, receipts, publication retries) that a team adopting Foundry wouldn't need.

## Decision

**Foundry is where evaluation runs and where results live.**

1. **Platform first, documentation first.** Use what Foundry and Agent Framework provide, the way Microsoft's documentation shows it: its commands, file layout and SDK calls. Write our own code only for a gap that's proven and recorded in [Foundry findings](../foundry-findings.md), with a link to the page it departs from.
2. **The design is two steps, which is proven:** Foundry calls the hosted agent on the evaluation dataset, then a second run scores the saved outputs with the judges and our code evaluators.
3. **A single run is iteration 5's first task, timeboxed.** If the agent call and all evaluators work in one run within the timebox, that becomes the design. Otherwise two steps stay.
4. **One recipe, one command.** An `eval.yaml` per agent, run with `azd ai eval` (or `azd ai agent eval`, whichever the current extension supports), following the [hosted agent evaluation quickstart](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent). No custom submission scripts beyond what a gap requires.
5. **The gate keeps ADR 0009's metrics:** minimum means for `hit_at_1_lenient`, `decisive_evidence_recall` and `evidence_grounded`, and `injection_resisted` as a hard check. They run as Foundry code evaluators with the answer key in the dataset. The gate decision itself (means and the hard check) is computed from the run's results by a small script, because Foundry reports pass counts per evaluator.
6. **Our code shrinks to the scoring functions and the dataset.** Reporting metrics that apply to every case come along in the same evaluation. Sparse reporting metrics (`ruled_out_correctly`, `data_quality_disclosed`) are dropped from Foundry until "doesn't apply" is handled. Sparse gate metrics run as separate evaluations over their applicable cases until then.
7. **Judges report, they don't gate.** ADR 0009's rule stands: a judge joins the gate only after its agreement with expert labels is measured.
8. **Agent Framework's `evaluate_agent` is the local counterpart,** for development runs with the same evaluators. It replaces our local harness, not Foundry.
9. **The local harness, the publisher and the spike scripts are retired** once the Foundry setup has measured the baseline. Until then `csai eval` stays as the fallback and the current gate.

**Naming in the Foundry project:**

| Item | Rule | Example |
|---|---|---|
| Evaluation | One per agent and suite | `rca-quality` |
| Run | Agent version and date | `rca-agent v12 2026-11-10` |
| Evaluator | One name per metric, a new version only when its code changes | `rca_hit_at_1_lenient` |
| Dataset | One name per case set, versioned with the cases | `rca-cases` v3 |

Spike items in the project are deleted after this decision, with the user's approval. The evidence stays in the results document.

## Consequences

- A team reading the sample sees the Foundry way to evaluate a hosted agent, plus a short, documented list of what we had to add and why.
- Iteration 5's scope is in the [backlog](../backlog.md#q-evaluation-you-can-trust): the adapter fix, the single-run attempt, one recipe, trimmed judge inputs, the gate script, the baseline in Foundry with repeats and comparison, `evaluate_agent` locally, then retiring our harness.
- Two steps cost a second run and a conversion of the saved tool calls. The conversion stays until Foundry's judges accept the Responses argument format.
- The gate depends on Foundry being available. ADR 0009's rule that the gate never depends on Foundry no longer holds; `csai eval` covers outages until it's retired.
- One 50-case run with four judges costs about 2.4M tokens at the measured rates (about 25k agent and 22k judge tokens per case), before trimming judge inputs. The baseline's three repeats need a budget decision.
- Thresholds stay provisional (0.70 / 0.65 / 0.85) until the baseline is measured in Foundry.
