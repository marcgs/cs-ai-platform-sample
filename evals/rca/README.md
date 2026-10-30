# RCA evaluations

The suite contains the original 18 cases (`SC-001` through `SC-018`) and unchanged
thresholds. Q2 changes the measuring harness, not the agent, cases or evaluators.
Regenerate the manifest with `uv run python -m rca_evals.manifest` after regenerating
the domain seed; do not hand-edit generated cases.

The harness accepts optional typed causal truth, explicit train/test assignments
and a fixed regression cohort for future suites. No challenge cases or new metrics
are introduced here. By default all cases gate; an extended suite must explicitly
set `EvalSuite.gate_case_ids` to retain the original regression cohort. Other cases
and their errors are informational. Selecting only report-only cases does not claim
that a regression gate passed.

## Repeated measurements

These commands use Azure models and the configured toolbox, not offline test data.
Serialize model traffic; do not run baseline and candidate concurrently.

```bash
uv run csai eval rca --target local --repeats 3 --concurrency 1 --split all \
  --agent-revision "$(git rev-parse HEAD)" \
  --output .eval-results/baseline/results.jsonl
```

`--agent-revision` records provenance; it does not check out or pin agent code.
Use the actual evaluated revision, and retain the harness patch when the checkout
is dirty. Hosted runs must identify the deployed revision explicitly.
`--model` records the model identity but does not configure it.

`--split train|test|all` defaults to `all`. Cases are grouped by machine, ranked by a
fixed salted hash and assigned approximately 2:1 train/test within categories.
Explicit manifest assignments are preserved; future manifest generators must retain
them when appending cases. Shared-machine constraints and small strata may prevent
balance, which produces a warning.

For local runs, `--episodes-output .eval-results/baseline/episodes.jsonl` additionally
exports real episodes, including failed attempts. It rejects hosted use and existing
destinations. Repeat with a distinct candidate output path; never overwrite a failed
run or rerun until green.

Each run writes:

- `results.jsonl`: one record per case/repeat, with structured errors and tool traces;
- `results.summary.json`: provenance, means, confidence intervals, groups and failures;
- `results.html`: an escaped static report;
- `results-transcripts/`: input, tool arguments/results, output and scores per case-run.

Artifacts are private and gitignored under `.eval-results/`. An incomplete tool
transcript is explicitly flagged, not treated as an empty successful trace.
All artifact destinations, including episode exports, must be distinct and unused.
Collisions are rejected before model calls; writers refuse to overwrite existing files.

## Errors and uncertainty

Retries are independent of repeats. Plumbing failures (rate limits, timeouts,
transport failures and missing/truncated output) retry with linear backoff. They
are excluded from quality denominators but still fail the regression gate.
Invalid structured output is scored, is not retried as plumbing, and fails the gate.
Automatic `wrong_answer` inference considers only metrics with declared minimums;
informational scores need not be higher-is-better.
Missing scores count as zero only for metrics with declared regression minimums.
Sparse informational means and intervals retain their applicable-score denominator.

Intervals are deterministic hierarchical case-then-repeat 95% percentile bootstrap
intervals: 2,000 draws, seed 42. Repeats do not become independent cases.
Small cohorts and synthetic data limit inference. Saturation and confidence widths
larger than the threshold margin produce warnings, not new thresholds.

## Paired comparison and keep/revert

Before measuring, declare a primary metric and practical noninferiority margins
for the other gated metrics. Retain the same cases, repeats, splits, metric semantics
and model configuration in baseline and candidate. Tune from train transcripts only;
do not inspect test transcripts while tuning.

`paired_difference_intervals` estimates candidate-minus-baseline intervals. It
rejects different non-plumbing regression case/repeat cohorts or metric applicability.
Do not silently drop plumbing failures to create a passing comparison.
If new informational metrics differ between runs, project both score maps onto the
same predeclared metrics, without changing their values or applicability:

```bash
uv run python - <<'PY'
from pathlib import Path

from cs_platform.evals import CaseResult, SuiteResult, paired_difference_intervals
from rca_evals import load_suite

metrics = set(load_suite().thresholds.minimums)

def load(path: str, split: str) -> SuiteResult:
    cases = [
        CaseResult.model_validate_json(line)
        for line in Path(path).read_text().splitlines() if line.strip()
    ]
    selected = [case for case in cases if case.gated and case.split == split]
    if not selected:
        raise ValueError(f"No regression case-runs for {split}")
    for case in selected:
        if case.output.failure and case.output.failure.kind == "plumbing":
            raise ValueError("Resolve plumbing failures before paired comparison")
        if not metrics <= case.scores.keys():
            raise ValueError("A predeclared metric is missing")
    return SuiteResult(suite="rca", cases=[
        case.model_copy(update={"scores": {name: case.scores[name] for name in metrics}})
        for case in selected
    ])

for split in ("train", "test"):
    baseline = load(".eval-results/baseline/results.jsonl", split)
    candidate = load(".eval-results/candidate/results.jsonl", split)
    print(split, paired_difference_intervals(baseline, candidate))
PY
```

Keep a change only if the primary metric's paired improvement interval has a lower
bound above zero on both train and test, the other gated metrics are noninferior
within their declared margins, and every unchanged threshold passes. Saturated
metrics require noninferiority, not impossible strict improvement. Otherwise revert
or investigate without claiming acceptance. This is the review rule, not an
additional automated CLI gate. Overlapping or unpaired intervals do not establish
improvement.

## Retained baseline

The unchanged `fae76ff` agent and dataset were measured on all 18 cases with three
repeats: all 54 diagnoses were correct, but historical-knowledge citations missed
their unchanged threshold. The run exited 1 and was retained, not rerun to seek a
pass. See [Q2 evidence](../../docs/iteration-3/q2.md) for scores and validation.
