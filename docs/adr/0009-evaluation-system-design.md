# ADR 0009: A small outcome gate locally, judges only in Foundry

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

`csai eval` scores every case with deterministic code checks against a closed
answer key. It produces about fifteen metrics, reports means with hierarchical
95% intervals and gates six metrics on the original 18 cases. Three of those six
(`tool_coverage`, `used_knowledge`, `schema_valid`) measure process or plumbing,
not whether the diagnosis is right.

Since iteration 4, each saved run can be published as one Foundry evaluation
run with two kinds of criteria:

- **Four built-in model judges** (task adherence, intent resolution, coherence,
  tool call accuracy). Foundry computes these.
- **Mirrors of local scores.** Each is a custom code evaluator whose `grade()`
  returns `item['scores'][metric]`. Foundry computes nothing for these.

Microsoft documents no way to import precomputed scores into a current Foundry
evaluation, so the mirrors are our own pattern. They can't carry metrics that
apply to only some cases: a code evaluator has no not-applicable result, and a
failing `grade()` is recorded as 0.0. Most of the publication work in iteration
4 went into the mirrors: sparse parity, calibration pass direction and a numeric
transport audit. None of it changed what we know about the agent.

Fewer metrics and mechanisms, each tied to an outcome, are easier to trust and
to act on. Fewer metrics need enough cases to mean something.

## Decision

**The gate is four outcome metrics, computed locally.**

| Metric | Question |
|---|---|
| `hit_at_1_lenient` | Right cause, an accepted alternative, or a justified abstention? |
| `decisive_evidence_recall` | Was the cause found for the right reason? |
| `evidence_grounded` | Does every cited reference exist? |
| `injection_resisted` | Did planted instructions get ignored? A hard check: one followed injection fails the gate |

- `schema_valid` becomes a plumbing check: an invalid report is a failure of
  the run, not a quality score.
- `hit_at_3`, `calibration`, `tool_coverage`, `knowledge_search_called`,
  `used_knowledge` and `data_quality_disclosed` stay in the report to explain
  failures. They don't gate.
- The first three gate on a minimum mean, with thresholds from a measured
  three-repeat baseline (Q4). `injection_resisted` has no threshold: any case-run
  that follows a planted instruction fails the gate. Four injection cases give
  a mean too wide an interval to gate on, and a safety check shouldn't average.

**Each mechanism has one job.**

| Mechanism | Job |
|---|---|
| `csai eval` | The only gate. Code checks, answer key, intervals, retained records, per-run HTML report |
| Foundry publication | Model judges on a saved run, visible next to the agent. No mirrors of local scores (Q16) |
| Score trend | One static page of the gated metrics per run over time, from retained records (Q17) |

Rules:

1. **The gate never depends on Foundry.** A publication failure or a judge score
   can't change the exit code of `csai eval`.
2. **A judge joins the gate only after** its agreement with expert labels is
   measured on the same cases.
3. **Grow cases, not metrics.** A new metric needs a decision it would change.

Parked, each kept as one line under the backlog's Later: Foundry-run agent
evaluation with ported code evaluators, Agent Framework `evaluate_agent` as the
runner, and continuous evaluation of live traffic. Safety evaluators and the
red-teaming agent stay with S2.

## Consequences

- The gate answers one question: is the diagnosis right, grounded and safe.
  A process regression shows in the report, not as a failed run.
- Q4 needs a new baseline and new thresholds, and the user's approval.
- The gate can't stay on the original 18: they are all clean cases, and none
  carries an injection. Each metric gates over every case it applies to.
  Injection gates as a hard check until enough injection cases exist for an
  interval to mean something.
- Foundry shows judges only. Our scores are in the local report and the trend.
- Removing the mirrors closes Q10 (sparse parity), Q14 (calibration pass
  direction) and Q15 (numeric transport) without further work. Their evidence
  stays in [iteration 4's Q9 record](../iteration-4/q9.md). The schema-4
  `calibration_score` grader in #26 is no longer needed.

## Sources

Microsoft Learn, checked 2026-11-03:

- [Custom evaluators (preview)](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators)
- [Evaluate existing datasets](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets)
- [Classic: evaluate locally and log to a project](https://learn.microsoft.com/azure/foundry-classic/how-to/develop/evaluate-sdk)
- [Agent Framework evaluation](https://learn.microsoft.com/agent-framework/agents/evaluation)
