# CI/CD

This exploration repository has **no active pipeline**. Quality is enforced locally, and the same gates are designed to move into CI unchanged.

## Local gates

| Gate | Command | When |
|---|---|---|
| Lint and format | `uv run ruff check`, `uv run ruff format --check` | Every commit (pre-commit) |
| Types | `uv run pyright` | Every commit (pre-commit) |
| Tests | `uv run pytest` | Before every commit |
| Agent quality | `csai eval` (exits non-zero below thresholds) | After changes to agents, tools, prompts or eval data |
| Deployment | `azd up` | When you want an environment |

Install the hooks once with `uv run pre-commit install`.

## Moving to a pipeline

When the sample becomes a reference for others, the gates map onto a pipeline (GitHub Actions or Azure Pipelines) like this:

1. **On every pull request:** lint, format check, type check and tests. Restore dependencies from a committed lock file generated against public PyPI (see ADR 0002 for what that requires).
2. **On pull requests that touch agents, tools, prompts or eval data:** deploy to a staging azd environment and run `csai eval`. The non-zero exit fails the pull request when quality regresses. Use path filters; evaluation runs cost model tokens.
3. **On merge to the main branch:** `azd provision` and `azd deploy`, then a smoke test that invokes the agent.
4. **Authentication:** the pipeline signs in to Azure with OpenID Connect (workload identity federation), not stored secrets, and its identity gets the same roles a developer gets from the infrastructure templates.
