# CS AI Platform sample

A reference sample that shows the path from **an agent prototype** to **an agent running on a governed Azure platform**. The platform gives the agent model access, tools, knowledge grounding, telemetry, evaluation gates, an episode/feedback trail and repeatable deployment. A fictional root-cause-analysis (RCA) diagnostics agent proves it works.

> All data in this repository is **synthetic and fictional**. It contains no customer data, names or machine types.

- What this is about: [`docs/specification.md`](docs/specification.md)
- Candidate Azure services: [`docs/azure-services-candidates.md`](docs/azure-services-candidates.md)
- Plan for iteration 1: [`docs/plan-iteration-1.md`](docs/plan-iteration-1.md)
- Decisions: [`docs/adr/`](docs/adr/)

## Repository layout

| Path | Purpose |
|---|---|
| `packages/cs-platform` | Reusable platform harness (agent specs, telemetry, episode capture) |
| `packages/diagnostics-domain` | Synthetic diagnostics domain, data generator and seed data |
| `docs/` | Plan, ADRs, architecture notes |

Further folders (`agents/`, `services/`, `evals/`, `cli/`, `infra/`) are added as the plan progresses.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.13+ (installs Python 3.14 automatically)

## Development

```bash
uv sync --all-packages        # create .venv with all workspace packages + dev tools
uv run pre-commit install     # recommended: lint/format/type checks on every commit

uv run ruff check             # lint
uv run ruff format            # format
uv run pyright                # type check (strict for packages/*/src)
uv run pytest                 # tests
```

There's no CI pipeline in this exploration repository: pre-commit hooks are the quality gate. See [`docs/ci-cd.md`](docs/ci-cd.md) for how the gates map onto a pipeline.

## Dependencies

`uv.lock` is local only (gitignored): everyone resolves against their own configured package index. See [`docs/dependencies.md`](docs/dependencies.md).
