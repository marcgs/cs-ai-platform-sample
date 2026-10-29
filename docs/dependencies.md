# Dependencies

Python dependencies are declared in the `pyproject.toml` files of the uv workspace. **`uv.lock` is local only: it's gitignored and never committed.** See [ADR 0002](adr/0002-local-lock-files.md) for the reasoning.

## Rules

- Use normal uv commands (`uv add`, `uv sync`, `uv run`). They resolve from whatever package index your machine is configured for, including an internal mirror.
- Give important dependencies a **minimum version** in `pyproject.toml` (`>=x.y`), so everyone gets a known-good baseline.
- Never commit `uv.lock`, and never put an index or mirror URL in a tracked file. Configure a mirror in your user-level uv config or with `UV_DEFAULT_INDEX`.
- If a minimum version isn't available yet from your mirror (mirrors often hold back new releases for a few days), wait or use the newest version that is available. Don't commit a mirror URL to work around it.

## Getting started

```bash
uv sync --all-packages   # resolves, creates .venv, writes a local uv.lock
```
