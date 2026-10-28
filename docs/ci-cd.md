# CI/CD

This exploration repository has **no active pipeline**. Quality is enforced locally, and the gates are commands that move into a pipeline unchanged.

## Local gates

| Gate | Command | When |
|---|---|---|
| Lint and format | `uv run ruff check`, `uv run ruff format --check` | Every commit (pre-commit) |
| Types | `uv run pyright` | Every commit (pre-commit) |
| Tests | `uv run pytest` | Before every commit |
| Agent quality, before deploying | `uv run csai eval rca --target local` | After changes to agents, tools, prompts, platform code or eval data |
| Agent quality, deployed | `uv run csai eval rca --target hosted` | After `azd deploy` |
| Deployment | `azd up` (or `azd provision` / `azd deploy <service>`) | When you want an environment or a new version |

Install the hooks once with `uv run pre-commit install`.

`csai eval` exits `1` when a metric is below its threshold (`evals/rca/src/rca_evals/thresholds.yaml`) or when cases errored after retries, and `2` when settings are missing. `--output results.jsonl` keeps per-case results, which a pipeline can publish as an artifact.

## Moving to a pipeline

The gates map onto a pipeline (GitHub Actions or Azure Pipelines) like this:

1. **On every pull request:** lint, format check, type check and tests. Restore dependencies from a committed lock file generated against public PyPI; ADR 0002 lists what that requires (a lock-generation workflow, a provenance check, restore-only use behind a mirror).
2. **On pull requests that touch `agents/`, `packages/`, `services/` or `evals/`:**
   - `csai eval rca --target local` against a shared staging Foundry project: fast, no deployment, catches prompt and code regressions.
   - Optionally deploy to a per-PR or staging azd environment and run `csai eval rca --target hosted`. Use path filters; each full run costs model tokens (about 18 × 12k tokens).
3. **On merge to the main branch:** `azd provision` and `azd deploy`, then `csai eval rca --target hosted` as the smoke test (or `--case SC-001` for a quick one).
4. **Authentication:** the pipeline signs in with OpenID Connect (workload identity federation), not stored secrets. Its identity needs the roles the templates give a developer (`principalId` in `infra/main.parameters.json`; set `AZURE_PRINCIPAL_TYPE=ServicePrincipal`), plus Contributor and User Access Administrator (or a constrained role-assignment role) on the subscription to provision.

### Network considerations

- Foundry, the container registry and AI Search are public with Entra-only access, so a hosted runner can provision, push images (built remotely in ACR) and deploy agents.
- The function apps deploy over their public SCM endpoint; the platform moves the package into the private storage account through the app's VNet integration. Hosted runners work.
- Cosmos DB and the functions' storage are private (ADR 0003). Nothing in the pipeline needs them directly; `csai episodes` reaches episodes through the platform API.
- Making Foundry and the registry private too (iteration 2) requires self-hosted runners inside the virtual network.

### Sketch (GitHub Actions)

Not active; for orientation only.

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
  agent-eval:
    needs: quality
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: Azure/setup-azd@v2
      - run: azd auth login --client-id ${{ vars.AZURE_CLIENT_ID }} --tenant-id ${{ vars.AZURE_TENANT_ID }} --federated-credential-provider github
      # csai reads its settings from the azd environment (endpoints, deployment names).
      - run: azd env refresh -e staging --no-prompt
      - run: uv sync --all-packages --locked
      - run: uv run csai eval rca --target local --output results.jsonl
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: eval-results, path: results.jsonl }
```
