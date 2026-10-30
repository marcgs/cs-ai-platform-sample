# diagnostics-domain

The fictional diagnostics fleet, reference catalog, seed scenarios and deterministic
data generators. The existing seed generator is unchanged.

## Synthetic feedback (L2)

No Azure, model calls or episode stores are used:

```bash
uv run generate-feedback --count 2000 --seed 42 --output-dir generated/synthetic-feedback
# Equivalent before installing the console script:
uv run python -m diagnostics_domain.feedback --count 2000 --seed 42
```

The destination must be empty. Generated populations stay out of git; the ten-episode
fixture under `tests/fixtures/feedback` is the small, committed example. Regenerate it
with the same command, count 10, seed 42, after removing its three files.

Files:

- `episodes.jsonl`: platform `Episode` records, explicitly `source: synthetic`.
- `reviews.jsonl`: `Review` records from `feedback_models.py`. Each has `id`,
  `episode_id`, `source` and a platform `Feedback` under `feedback`. Several reviews
  can refer to an episode. Exact duplicate IDs and copied reviews with different IDs
  intentionally occur. `Episode.feedback` is the first review, not a consensus.
- `answer_key.json`: `AnswerKey`, separate from classifier inputs. Each `PlantedPattern`
  has `id`, `description`, `classification`, `route`, `episode_ids`. Each `EpisodeTruth`
  has the episode ID, optional pattern ID, expected and actual failure-mode IDs,
  verdict, machine, platform, software release and historical downtime proxy.
  **Actual failure mode means the agent's reported first hypothesis**, not truth.
  Expected failure mode is the planted truth; `unknown` is the safe response to the
  data-quality variant. Routes are `learner`, `knowledge` or `backlog`.

The stable pattern IDs are `vacuum_telemetry_omission`,
`overlapping_codes_after_update`, `missing_code_mapping`, `data_quality` and
`injection_followed`. The taxonomy and review/key shapes are typed in
`feedback_models.py`, which L3 imports rather than redefining.

Every ten records contain five misses and five matched correct controls, over
seed-scenario machines and causal failure modes. Pattern variants overlay transcript
data; they do not mutate the seed dataset. The post-update variant uses the same
update date in machine context and its logbook entry, for misses and controls.
IDs, tool timings, timestamps and reviews
depend only on the seed, index and committed seed data. More records preserve the
existing prefix. The displayed telemetry windows are compact transcript excerpts.

Four fictional reviewers have different accuracy; `R-004` is deliberately too strict.
Disagreements, incomplete notes, wrong actual-cause assertions and duplicates are
intentional. The answer key records generator truth independently of those assertions.
Do not treat reviews or their first embedded copy as authoritative labels.

`write_feedback` and `load_feedback` refuse wrong-source or dangling review records.
For real local runs, use `cs_platform.episode_io.export_episodes` into
`generated/real-episodes/`, never the synthetic destination. Import requires an
explicit matching source label on every episode. These helpers never write to an
episode store or combine populations; synthetic data is not a real eval gate.

The local `csai diagnose` / `csai eval` episode-export flags are a cross-topic
dependency supplied by Q2; this branch is stacked on that implementation.
They are not part of the L2 diff. Library export and synthetic generation work
without that CLI dependency.
See [L2 validation and publication dependencies](../../docs/iteration-3/l2.md).

The domain package depends on the platform's episode boundary models. The platform
does not depend on this domain or import its generator.
