# ADR 0007: Foundry evaluation with an answer-key gate and measured thresholds

- **Status:** Accepted
- **Date:** 2026-11-05

## Context

The RCA agent needs a repeatable check of diagnostic correctness and evidence, not just whether an answer reads well. The 50 synthetic cases already carry the expected outcome and evidence references. Use the [hosted-agent evaluation quickstart](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent), writing our own code only for proven gaps.

## Decision

- Foundry calls the **deployed hosted agent** on the cases through `azd ai eval`, configured in `evals/azure.eval.yaml`. Rows come from the generated local `queries.jsonl`, including their answer keys and metric applicability. There is no client-side agent harness or rescoring pass.
- Two built-in judges, **intent resolution** and **task adherence**, report on the final answer. They are diagnostic, not acceptance criteria.
- Six **code evaluators** score against the answer key: `hit_at_1`, `hit_at_1_lenient`, `hit_at_3`, `decisive_evidence_recall`, `evidence_grounded` and `injection_resisted`. They run in Foundry, use no model tokens, and are generated from the offline-tested graders. References are supplied in the rows; no evaluator reaches into source systems.
- **`rca_evals.gate` decides pass or fail**, reading saved output items without writes, model calls, retries or repairs. It takes applicability-filtered means for lenient top-1, decisive-evidence recall and grounding, and requires every applicable injection score to be 1.0. Agent-call failures and gate-evaluator errors fail independently of quality; other evaluator errors remain visible diagnostics. Missing or invalid gate data fails closed.
- The installed azd gate counts **passed cases divided by all cases**. It cannot express separate per-metric means, applicability, a hard injection check and diagnostic-only evaluators, so it cannot make this decision ([finding](../foundry-findings.md#azds-pass-rate-gate-cannot-express-the-rca-gate)).
- `evals/rca/gate.json` is the gate's configuration. For each mean-gated metric, subtract 0.05 from the lowest of the three run means and round down to the nearest 0.05; injection resistance remains a hard check. The [first measurement](../../evals/rca/README.md#first-measurement) records the inputs, spreads and thresholds.
- The minimum-mean thresholds derived from this measurement are **0.75** for `hit_at_1_lenient`, **0.70** for `decisive_evidence_recall` and **0.85** for `evidence_grounded`; `injection_resisted` requires every applicable score to be **1.0**. All three accepted runs pass. One attempt with agent-call failures was excluded and replaced only after approval.

## Consequences

- Three 50-case runs of agent version 8 are a **first baseline, not a statistical guarantee**. The gate is a minimum-quality check, not proof of improvement or a calibrated model-judge verdict. New agents need their own cases, evaluators and measured criteria.
- The portal is useful for inspecting individual results, but its headline pass count is not our acceptance result. Execution failures must not be interpreted as wrong diagnoses.
- A full run costs about $1 with gpt-5.4-mini (Data Zone); checking saved results costs $0 in model calls. Get approval before runs, and inspect the [evaluation findings](../foundry-findings.md#evaluation) first.
- The [findings](../foundry-findings.md#evaluation) hold the platform limitations and workarounds. The [evaluation storage exception](0006-evaluation-storage-network-exception.md) remains unchanged.
- Commands can move into a pipeline, but **no pipeline is active**. The [CI/CD sketch](../ci-cd.md) shows the evaluation job without adding a workflow.
