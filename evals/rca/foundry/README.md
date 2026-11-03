# Foundry agent-target evaluation

This is separate from the local harness. Foundry reaches the hosted agent.
The approved two-pass workflow scores all four built-in judges on retained,
losslessly normalized tool calls. The original single-pass failures stay evidence. See
[results](../../../docs/spike-foundry-native-eval-results.md).
Do not resubmit it to repair scores.

`eval.yaml` is the current `azd ai eval` recipe. The removed
`azd ai agent eval` command only prints migration guidance.
The evaluation uses five unchanged synthetic cases, their answer keys and
tool schemas retained from the reference measurement.

Regenerate the dataset without model calls:

```bash
uv run python evals/rca/foundry/prepare.py \
  --reference <private-reference-results.run> --output evals/rca/foundry/datasets
```

Render environment-specific values into a private copy, never the tracked recipe:

```bash
uv run python - <<'PY'
import os
from pathlib import Path
from string import Template

from csai.environment import load_environment

load_environment()
base = Path("evals/rca/foundry").resolve()
private = Path(".eval-results/foundry-native")
private.mkdir(parents=True, exist_ok=True)
recipe = Template((base / "eval.yaml").read_text()).substitute(os.environ)
recipe = recipe.replace("datasets/smoke.jsonl", str(base / "datasets/smoke.jsonl"))
(private / "eval.yaml").write_text(recipe)
PY
```

After model/write approval, create and submit **once**, retaining the returned IDs:

```bash
export FOUNDRY_PROJECT_ENDPOINT="$(azd env get-value FOUNDRY_PROJECT_ENDPOINT)"
azd ai eval create --from-file .eval-results/foundry-native/eval.yaml \
  --project-endpoint "$FOUNDRY_PROJECT_ENDPOINT"
azd ai eval run start --path .eval-results/foundry-native/eval.yaml \
  --eval rca-native-smoke-judges --project-endpoint "$FOUNDRY_PROJECT_ENDPOINT" --no-wait
```

The CLI's `init` command rewrites the root `azure.yaml`; it is not needed for this
authored recipe. No provisioning or deployment command is part of this flow.

Inspect the same run without more agent/judge calls:

```bash
uv run python evals/rca/foundry/results.py \
  --evaluation <evaluation-id> --run <run-id> \
  --output .eval-results/foundry-native/step1 --wait
```

The reader saves raw run/output data and reports every missing or errored judge.
Exit 1 means incomplete judge execution or a non-completed run; exit 3 means still
running without `--wait`. Neither means resubmit. Numeric low scores are results,
not execution errors. Token totals conservatively include every service usage
entry, even apparent aliases; cumulative allowance must be checked before another run.
Private receipts and portal URLs stay out of git.

## Approved two-pass judging

Prepare saved outputs offline; this does not repeat the agent:

```bash
uv run python -m evals.rca.foundry.normalize \
  --source .eval-results/foundry-native/step1/outputs.json \
  --output .eval-results/foundry-native/normalized.jsonl
```

Only argument representation changes. Repeated complete objects must be identical;
conflicting, non-object or malformed arguments stop preparation.
Render `eval-replay.yaml` with the same environment substitution as above, also
setting `FOUNDRY_NATIVE_NORMALIZED_DATA` to the normalized JSONL's absolute path.
Create/start that recipe once with `azd ai eval`. It has no agent target: only
the four judges consume tokens. Inspect its retained ID with `results.py`.

## Native code metrics and identical-output parity

The bundle uses the actual local evaluator/model source, not precomputed scores.
Dataset answer keys supply truth, valid reference IDs and causal logbook text.
The source bundle's seed-access adaptations are checked against local scoring.

Prepare the normalized dataset without model calls:

```bash
uv run python -m evals.rca.foundry.graders \
  --source .eval-results/foundry-native/normalized.jsonl \
  --output .eval-results/foundry-native/scoring.jsonl
```

After project data-plane write approval, register code evaluator versions and
submit dense or applicable-only sparse evaluations. These static code runs do
not invoke the agent or model judges:

```bash
uv run python -m evals.rca.foundry.submit_metrics \
  --dataset .eval-results/foundry-native/scoring.jsonl \
  --receipts .eval-results/foundry-native/metrics --scope dense
uv run python -m evals.rca.foundry.submit_metrics \
  --dataset .eval-results/foundry-native/scoring.jsonl \
  --receipts .eval-results/foundry-native/metrics --scope sparse
```

Dense metrics: strict/lenient top-one and top-three correctness, grounded
evidence, schema validity, tool coverage, knowledge search/use and
`calibration_score = 1 - Brier`. Sparse metrics: decisive evidence recall,
injection resistance, data-quality disclosure and ruled-out correctness.
Each sparse definition receives only applicable rows; empty subsets are not
submitted. Invalid-report handling matches local scoring.
Foundry's row pass threshold is not the local aggregate outcome gate.

Receipts are written before submission. An existing receipt is never resubmitted,
including an ambiguous pending receipt. Inspect/reconcile it rather than
discarding it. Use `results.py --metric <name>` for every expected metric
(`--metric` can repeat), then verify the actual service scores:

```bash
uv run python -m evals.rca.foundry.parity \
  --results <private-metric-outputs.json> \
  --dataset .eval-results/foundry-native/scoring.jsonl \
  --output <private-parity.json>
```

Every per-case difference must be at most `1e-12`; missing/error scores fail.
Both CLI and SDK source-item shapes are supported.

For genuinely new applicable cases, `prepare.py --case <suite-case-id>` can
repeat. Use the existing CLI target recipe with that new dataset, then normalize,
augment and grade the retained outputs as above. **New target runs consume
model tokens** and need the same approval/budget check as any agent run.
`submit_metrics --scope sparse --metric <name>` selects just one static metric.
Never regenerate retained outputs to improve scores.
