# Foundry agent-target evaluation

This is separate from the local harness. The first run reached the hosted agent,
but two built-in judges failed on tool argument serialization. See
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
