# CI/CD

This repository has **no active pipeline**. The gates are local commands that move into a pipeline unchanged.

| Gate | Command | When |
|---|---|---|
| Lint, format, types | `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` | Every commit (pre-commit hooks: `uv run pre-commit install`) |
| Tests | `uv run pytest` (offline) | Before every commit |
| Local smoke test | `azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"`, then `azd ai agent invoke --local "…"` | After changing agents, tools, prompts or platform code |
| Deployed smoke test | `azd ai agent invoke "…"` | After `azd deploy` |
| Evaluation | The [README's commands](../README.md#evaluate), ending in `uv run python -m rca_evals.gate --run <run-name>` (exit 1 on FAIL) | After behavior, tool or case changes; about $1 per run, with approval |

## Moving to a pipeline

1. **Every pull request:** lint, types and tests. This needs a committed lock file generated against public PyPI, with the extra machinery [ADR 0002](adr/0002-local-lock-files.md) describes.
2. **Pull requests that touch `agents/`, `packages/`, `services/`, `evals/` or `cli/`:** after approval, deploy to a staging azd environment, start an evaluation run with a unique name, wait for that run with the SDK (azd can't read local-source runs back, see [findings](foundry-findings.md#azd-ai-eval-is-an-early-beta)), then run the gate on it. Serialize jobs in a shared environment: azd evaluates the latest agent version.
3. **Merge to the main branch:** `azd provision` and `azd deploy`, then `azd ai agent invoke` with one known case.
4. **Authentication:** OpenID Connect (workload identity federation), no stored secrets. The pipeline's identity needs the developer roles the templates grant (`principalId` in `infra/main.parameters.json`, with `AZURE_PRINCIPAL_TYPE=ServicePrincipal`), plus Contributor and User Access Administrator (or a constrained role-assignment role) to provision.

**Network:** Foundry, the registry and AI Search are public with Entra-only access, and function apps deploy over their public SCM endpoint, so hosted runners work. Nothing in the pipeline needs the private Cosmos DB or storage directly. Making Foundry and the registry private would need self-hosted runners in the virtual network.
