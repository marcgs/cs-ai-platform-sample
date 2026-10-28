# ADR 0002: Lock files stay local

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

uv records the index URL and the download URL of every artifact in `uv.lock`. Some contributors work on machines that must download packages through an internal mirror, so any lock file they generate contains the mirror's URLs. Committing such a lock file would:

- leak internal hostnames into the repository,
- tie restores to infrastructure that others can't reach.

Committing only lock files generated against public PyPI avoids this, but it needs extra machinery: a lock-generation pipeline, a provenance check, and a restore-only workflow on restricted machines. That's justified for a repository others build on. It's too much overhead for an exploration sample.

## Decision

- `uv.lock` is gitignored. Every developer resolves locally against their own configured index.
- `pyproject.toml` files declare minimum versions for the dependencies that matter.
- No index or mirror URL appears in any tracked file.
- There's no CI pipeline in this repository (see [`docs/ci-cd.md`](../ci-cd.md)), so nothing depends on a committed lock file.

## Consequences

- Builds aren't byte-for-byte reproducible across machines; two developers may get different patch versions. Pinning a specific package fixes this where it matters.
- If the sample becomes a reference for others, switch to committed lock files generated against public PyPI: a lock-generation workflow, a provenance check that only allows `pypi.org` and `files.pythonhosted.org`, and restore-only use (`UV_FROZEN=1`) on machines that must use a mirror.
- Container images don't resolve packages on their own: the agent's `prepackage` hook exports the local lock to a requirements file with exact versions and hashes but without index URLs, so images run the locally tested versions without exposing the mirror.
