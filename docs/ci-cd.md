# CI/CD

This exploration repository has **no active pipeline**. Quality is enforced locally, and the gates are commands that move into a pipeline unchanged.

## Local gates

| Gate | Command | When |
|---|---|---|
| Lint and format | `uv run ruff check`, `uv run ruff format --check` | Every commit (pre-commit) |
| Types | `uv run pyright` | Every commit (pre-commit) |
| Tests | `uv run pytest` | Before every commit |
| Agent smoke test, before deploying | `azd ai agent run`, then `azd ai agent invoke --local "…"` | After changes to agents, tools, prompts or platform code |
| Agent smoke test, deployed | `azd ai agent invoke "…"` | After `azd deploy` |
| Deployment | `azd up` (or `azd provision` / `azd deploy <service>`) | When you want an environment or a new version |

Install the hooks once with `uv run pre-commit install`.

There's no quality gate on agent behavior yet: evaluation is being rebuilt with Foundry evaluation ([plan](plan-evaluation.md)). Foundry documents a pass-rate quality gate for pipelines with `azd ai eval`; it will slot in where the smoke tests are below.

## Moving to a pipeline

The gates map onto a pipeline (GitHub Actions or Azure Pipelines) like this:

1. **On every pull request:** lint, format check, type check and tests. Restore dependencies from a committed lock file generated against public PyPI; ADR 0002 lists what that requires (a lock-generation workflow, a provenance check, restore-only use behind a mirror).
2. **On pull requests that touch `agents/`, `packages/`, `services/` or `evals/`:** deploy to a per-PR or staging azd environment and run the evaluation there, once it exists. Use path filters; each run costs model tokens.
3. **On merge to the main branch:** `azd provision` and `azd deploy`, then `azd ai agent invoke` with one known case as the smoke test.
4. **Authentication:** the pipeline signs in with OpenID Connect (workload identity federation), not stored secrets. Its identity needs the roles the templates give a developer (`principalId` in `infra/main.parameters.json`; set `AZURE_PRINCIPAL_TYPE=ServicePrincipal`), plus Contributor and User Access Administrator (or a constrained role-assignment role) on the subscription to provision.

### Network considerations

- Foundry, the container registry and AI Search are public with Entra-only access, so a hosted runner can provision, push images (built remotely in ACR) and deploy agents.
- The function apps deploy over their public SCM endpoint; the platform moves the package into the private storage account through the app's VNet integration. Hosted runners work.
- Cosmos DB and the functions' storage are private (ADR 0003). Nothing in the pipeline needs them directly; `csai episodes` reaches episodes through the platform API.
- Making Foundry and the registry private too requires self-hosted runners inside the virtual network.

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
```

The agent evaluation job is added once evaluation is rebuilt.
