# Synthetic diagnostics dataset

All machines, incidents and records are fictional. Generate the committed seed with
`uv run generate-seed-data`; do not edit `data/seed.json`.

## Dataset card

The seed contains 56 machines and 50 eval incident scenarios:

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

Four additional feedback-only machines (`M-0053`–`M-0056`) copy clean telemetry and
service clues under new record IDs. Their events use `EC-9901`, a documented code
without mapped causes. They add no eval scenarios and change no existing records
or tool responses. `feedback_seed.py` appends these records during seed generation.
Copied feedback scenarios remap their decisive telemetry, event and logbook
references to those feedback-only records, not the original machines' evidence.

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

## Synthetic feedback

A large population of episodes with expert reviews and planted patterns, for developing failure analysis (backlog L3) without real feedback. No Azure, model calls or episode stores are used:

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
`feedback_models.py`.

Every ten records contain five misses and five matched correct controls, over
seed machines and causal failure modes. Every captured result is returned by
`diagnostics_domain.tools.DiagnosticsTools`, the same implementation re-exported
by the MCP service. Update, injection and data-quality contexts use the existing
`overlapping`, `injection` and `data_gap` seed cohorts. Missing-mapping contexts use
the four additive feedback machines. There are no transcript-only data overlays
or deliberately non-replayable episodes in new populations.
Vacuum omissions select clean vacuum incidents, not injection/sensor contexts.
Update contexts require an observed shared code and record that actual lookup.
IDs, tool timings, timestamps and reviews
depend only on the seed, index and committed seed data. More records preserve the
existing prefix within this generator version. Telemetry windows use actual tool
summaries and sample references, not synthetic excerpts.
Correct missing-mapping controls cite real telemetry and service clues. The old
generator's invented `azure_ai_search` responses are not retained: the five MCP
tools cannot reproduce a live search response. The failed variant still returns
unknown despite a supported signature. The L2 example fixture is regenerated;
L3's published pilot outputs remain frozen and are not replay-compatible inputs.

`diagnostics_domain.feedback_replay` exports `replay_episode`, `execute_tool_call`,
`tool_fingerprint`, `ReplayResult` and `ReplayIssue` for offline promotion checks.
`replay_episode(episode, *, tools=None)` defaults to today's committed seed. Its
result carries `replayable`, ordered `fingerprints` and indexed rejection `issues`.
Unsupported tools, incomplete/truncated captures, invalid JSON and changed
results are rejected. Tool fingerprints hash normalized name, arguments and
canonical JSON results, ignoring timing and the toolbox's `___` prefix.
These checks do not establish reviewer consensus or promotion eligibility.

Four fictional reviewers have different accuracy; `R-004` is deliberately too strict.
Disagreements, incomplete notes, wrong actual-cause assertions and duplicates are
intentional. The answer key records generator truth independently of those assertions.
Do not treat reviews or their first embedded copy as authoritative labels.

`write_feedback` and `load_feedback` refuse wrong-source or dangling review records.
For real local runs, use `cs_platform.episode_io.export_episodes` into
`generated/real-episodes/`, never the synthetic destination. Import requires an
explicit matching source label on every episode. These helpers never write to an
episode store or combine populations; synthetic feedback is never treated as real.

The domain package depends on the platform's episode boundary models. The platform
does not depend on this domain or import its generator.
