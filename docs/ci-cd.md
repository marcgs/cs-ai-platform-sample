# CI/CD

This exploration repository has **no active pipeline**. Quality is enforced locally, and the gates are commands that move into a pipeline unchanged.

## Local gates

| Gate | Command | When |
|---|---|---|
| Lint and format | `uv run ruff check`, `uv run ruff format --check` | Every commit (pre-commit) |
| Types | `uv run pyright` | Every commit (pre-commit) |
| Tests | `uv run pytest` | Before every commit |
| Agent smoke test, before deploying | `azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"`, then `azd ai agent invoke --local "…"` | After changes to agents, tools, prompts or platform code |
| Agent smoke test, deployed | `azd ai agent invoke "…"` | After `azd deploy` |
| Deployed-agent evaluation | [README run command](../README.md#evaluate), then `uv run python -m rca_evals.gate --run <run-name>` | After behavior, tool or case changes; approval first, about $1 per 50-case run |
| Deployment | `azd up` (or `azd provision` / `azd deploy <service>`) | When you want an environment or a new version |

Install the hooks once with `uv run pre-commit install`.

The evaluation gate reads saved Foundry results and exits 0 for PASS or 1 for FAIL: applicability-filtered minimum means, a hard injection check, and agent/gate-evaluator execution errors separate from wrong answers. Other evaluator errors are diagnostic. Its thresholds come from the [three-run first baseline](../evals/rca/README.md#first-measurement), not a statistical guarantee. azd's pass-rate gate cannot express that policy ([ADR 0011](adr/0011-foundry-evaluation-and-measured-gate.md)). Read the [known failures](foundry-findings.md#evaluation) before each model-token run.

## Moving to a pipeline

The gates map onto a pipeline (GitHub Actions or Azure Pipelines) like this:

1. **On every pull request:** lint, format check, type check and tests. Restore dependencies from a committed lock file generated against public PyPI; ADR 0002 lists what that requires (a lock-generation workflow, a provenance check, restore-only use behind a mirror).
2. **On pull requests that touch `agents/`, `packages/`, `services/` or `evals/`:** after approval, deploy to a per-PR or staging azd environment and run the evaluation there. Wait for that exact run with the SDK, then call `uv run python -m rca_evals.gate --run <run-name>`; do not check an older completed run by accident. Use path filters and unique run names; each run costs about $1 in model tokens. Serialize deployments and evaluations in a shared staging environment: azd targets the latest agent version.
3. **On merge to the main branch:** `azd provision` and `azd deploy`, then `azd ai agent invoke` with one known case as the smoke test.
4. **Authentication:** the pipeline signs in with OpenID Connect (workload identity federation), not stored secrets. Its identity needs the roles the templates give a developer (`principalId` in `infra/main.parameters.json`; set `AZURE_PRINCIPAL_TYPE=ServicePrincipal`), plus Contributor and User Access Administrator (or a constrained role-assignment role) on the subscription to provision.

### Network considerations

- Foundry, the container registry and AI Search are public with Entra-only access, so a hosted runner can provision, push images (built remotely in ACR) and deploy agents.
- The function apps deploy over their public SCM endpoint; the platform moves the package into the private storage account through the app's VNet integration. Hosted runners work.
- Cosmos DB and the functions' storage are private (ADR 0003). Nothing in the pipeline needs them directly; `csai episodes` reaches episodes through the platform API.
- Making Foundry and the registry private too requires self-hosted runners inside the virtual network.

### Sketch (GitHub Actions)

Not active; for orientation only. Authentication, approved staging-environment setup and deployment steps are omitted. The evaluation job assumes the extensions are installed, both azd and Azure CLI are signed in through OIDC, the azd environment is selected, and `rca-quality` has been created once there. The committed-lock restore below also needs the ADR 0002 work described above before activation.

```yaml
on:
  pull_request:
    paths: ["agents/**", "packages/**", "services/**", "evals/**", "cli/**"]
permissions:
  id-token: write
  contents: read
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --all-packages --locked
      - run: uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest
  evaluation:
    needs: quality
    runs-on: ubuntu-latest
    environment: staging # require approval for deployment and model spend
    concurrency:
      group: rca-staging-evaluation
      cancel-in-progress: false
    env:
      EVAL_RUN_NAME: rca-pr-${{ github.run_id }}-${{ github.run_attempt }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: Azure/setup-azd@v2
      - run: uv sync --all-packages --locked
      # Approved OIDC login, azd environment selection and staging deployment go here.
      - run: azd ai eval run start --no-wait --name "$EVAL_RUN_NAME"
      - name: Wait for this run with the SDK (azd local-source readback is broken)
        timeout-minutes: 45
        run: |
          uv run python - <<'PY'
          import os
          import subprocess
          import time
          from azure.ai.projects import AIProjectClient
          from azure.identity import AzureCliCredential

          endpoint = subprocess.check_output(
              ["azd", "env", "get-value", "FOUNDRY_PROJECT_ENDPOINT"], text=True
          ).strip()
          with AzureCliCredential() as credential, AIProjectClient(
              endpoint=endpoint, credential=credential
          ) as project, project.get_openai_client(max_retries=0) as client:
              evaluation = max(
                  (e for e in client.evals.list() if e.name == "rca-quality"),
                  key=lambda e: e.created_at,
              )
              runs = [
                  r for r in client.evals.runs.list(eval_id=evaluation.id)
                  if r.name == os.environ["EVAL_RUN_NAME"]
              ]
              if len(runs) != 1:
                  raise RuntimeError("Expected exactly one run with this name")
              run = runs[0]
              while run.status in {"queued", "in_progress"}:
                  time.sleep(60)
                  run = client.evals.runs.retrieve(run.id, eval_id=evaluation.id)
              if run.status != "completed":
                  raise RuntimeError(f"Run ended: {run.status}")
          PY
      - run: uv run python -m rca_evals.gate --run "$EVAL_RUN_NAME"
```

The SDK wait only reads status; the final gate checks per-row execution errors and scores even when Foundry reports `completed`. Nothing in this sketch is an active workflow, and it adds no automatic retries or resubmissions.
