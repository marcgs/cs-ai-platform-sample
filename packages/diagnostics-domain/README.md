# Synthetic diagnostics dataset

All machines, incidents and records are fictional. Generate the committed seed with
`uv run generate-seed-data`; do not edit `data/seed.json`.

## Dataset card

The seed contains 52 machines and 50 incident scenarios:

| Category | Cases | Causal distinction |
|---|---:|---|
| `clean` | 18 | Original eight physical and software failure modes |
| `overlapping` | 4 | Shared alarms and recent updates; discriminating telemetry |
| `no_fault_found` | 4 | Healthy telemetry and independent checks |
| `out_of_catalog` | 4 | Unmapped code and a non-catalog residual |
| `missing_machine` | 4 | No identifier or timestamp in the rendered incident |
| `injection` | 4 | Untrusted instructions inside logbook text |
| `sensor_fault` | 4 | Stuck or drifting primary pressure sensor, healthy reference |
| `data_gap` | 4 | Missing samples, duplicate observations, delayed events, clock reversal |
| `nuisance_alarm` | 4 | Flapping or authorized maintenance alarms on healthy machines |

`Scenario` carries generator-derived category, decisive evidence references, acceptable
alternatives, ruled-out modes and confirming checks. `incident_input()` is the input
rendering contract: missing-machine incidents withhold their hidden machine identity.
No-fault, out-of-catalog, missing-machine, collector faults and nuisance alarms expect
`unknown`; this does not add a failure mode to the physical catalog.

The original random stream, IDs and records are preserved. Challenge cohorts use independent
seeded streams per category, machines from `M-0021`, scenarios from `SC-019`, events above
`EV-100000` and logbook IDs above `LB-10000`. New sensor capability is advertised only for
machines that have its telemetry. Legacy regular telemetry keeps its original serialization.
Irregular series carry observation timestamps alongside values: removing samples never
compresses elapsed time. Events optionally carry receipt time, distinct from event time.
Original and injection-cohort precursor clues remain before onset. Retrospective
investigations are logged after their telemetry observations and event receipts,
before incident reporting. Maintenance findings follow the completed window and
the subsequent healthy checks.

The frozen `services/diagnostics-mcp/tests/fixtures/legacy_golden.json` records hashes taken
from revision `fae76ff`, before extension: all original seed fields and 791 tool responses
across original scenarios, signals, catalog codes and several windows. Do not regenerate it
to accept a regression.

Known biases: four examples per new category are small, templated cohorts, not measured
field frequencies. Causes, checks and wording are generator-authored. Cases have one
preferred explanation, healthy reference gauges are unusually reliable, and injection
canaries are deliberately recognizable. Out-of-catalog cases model an unknown cause,
not a validated new failure mode. Dataset counts and category balance imply no real-world
prevalence. Train/test assignment is owned by the eval manifest; tuning must use train only.

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
Correct missing-mapping controls also record `azure_ai_search` retrieval of a
matching seeded historical case and cite its returned `HC-…` ref and resolution.
The failed variant lacks that successful knowledge fallback.
Only this missing-mapping cohort requires a matching seeded historical case when
choosing scenarios, for both misses and controls. Other contexts retain their
existing eligibility rules and can select new known causes without prior cases.

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
