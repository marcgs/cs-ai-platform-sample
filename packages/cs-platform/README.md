# cs-platform

The reusable agent harness. An agent is declared by a spec and built by the platform, which wires in the cross-cutting capabilities once for every agent.

| Module | Provides |
|---|---|
| `spec.py` | `AgentSpec` and `load_spec()`: name, version, description, instructions file, tool sources, eval suite |
| `settings.py` | `PlatformSettings.from_env()`: Foundry project and model deployment, toolbox/MCP endpoint, Cosmos DB, Application Insights |
| `factory.py` | `build_agent()`, plus `foundry_client()` and `episode_store()` for the Azure-backed defaults |
| `retry.py` | A bounded, asynchronous 429-only retry policy for one Foundry model turn |
| `capture.py` | Middleware that records every run as an episode: input, tool calls (arguments, result, duration, errors), structured output, token usage, trace ID |
| `episodes.py` | `Episode`, `ToolCall`, `Feedback`; the `EpisodeStore` protocol with in-memory and Cosmos DB implementations |
| `episode_io.py` | Explicitly source-separated local JSONL export/import, without accessing an episode store |
| `hosting.py` | Bind each host-issued Responses ID to its exact episode, independently of input, timing or session |
| `evals.py` | Eval harness: `EvalCase`, `EvalSuite` (cases, thresholds, evaluators), `run_suite()` with concurrency and retries, `SuiteResult` with metrics and gate failures |
| `evidence.py` | `Evidence`: the cited unit (source, ref, excerpt) agents put in their output and evaluators verify |
| `telemetry.py` | `configure_telemetry()` for processes outside Foundry hosting: Azure Monitor export plus agent instrumentation |

```python
spec = load_spec(Path("agents/rca/agent.spec.yaml"))
settings = PlatformSettings.from_env()
agent = build_agent(
    spec,
    client=foundry_client(settings, credential),
    store=episode_store(settings, credential),
    tools=[diagnostics_tools],
    response_format=RcaReport,
)
response = await agent.run("M-0001: overlay drift and stage temperature alarm")
episode_id = response.additional_properties["episode_id"]
```

Capture is deterministic: the platform writes the episode, not the model. A failing episode store is logged and never fails the user's request.

`Episode.source` defaults to `real` for actual runs (including runs against the fictional
diagnostics seed). Simulated runs must set it to `synthetic`. Legacy records still read
as real. `export_episodes(episodes, path)` writes explicit real labels and refuses
synthetic records, mixed populations and existing files. Set `source="synthetic"`
explicitly for a separate synthetic population. `load_episodes` requires every record
to have an explicit matching label. Neither helper connects to or mutates a store.
See the [synthetic feedback generator](../diagnostics-domain/README.md).

`foundry_client()` disables the OpenAI SDK's broader automatic retries and retries only
model 429s: at most four attempts and 120 seconds of total waiting per turn. Server
`Retry-After` (seconds or HTTP date) and millisecond delays take precedence over exponential
backoff with jitter. A server delay exceeding the remaining wait budget ends the turn;
it is never shortened. Cancellation and non-429 failures propagate immediately.
Streaming retries stop at the first update, even metadata-only output. Tools and earlier
model turns are never replayed. The successful stream's original finalizer is preserved.

Each 429 produces a sanitized warning and a `cs_platform.model.rate_limit` span event
with attempt, delay, retry decision and whether streaming output was emitted. Recovered
runs remain successful; exhausted runs retain the existing failed-episode recording.
This does not change model capacity. Hosted validation and the live eval gate require
a separately approved feature deployment and serialized model traffic; offline checks
do not establish those acceptance results.

Metric means use `statistics.mean`, which preserves summation accuracy before converting
the mean to a float. This matters at exact gate boundaries: nine scores of `0.8` and nine
of `1.0` average to `0.9`, but naive floating-point summation can report
`0.8999999999999999`. Comparisons remain strict: no tolerance, rounding of case scores,
or relaxed threshold makes a genuinely lower score pass.

## Evaluation health

`run_suite(..., repeats=3)` runs independent case-runs; retries remain separate.
Quality means exclude plumbing failures (rate limits, timeouts, transport failures and
missing/truncated output), but those failures still fail the regression gate. Invalid
structured output remains a scored quality failure. `RunOutput.failure` classifies errors;
`tool_trace` retains typed calls with arguments and results alongside legacy tool names.

`EvalSuite.gate_case_ids` declares the fixed regression cohort. Its default (`None`) gates
all cases for legacy suites. Extended suites must explicitly retain their original case
IDs: new categories, including their errors, are informational only, never pooled into
thresholds. Only metrics with declared minimums zero-fill missing scores.
`run_suite` records those names in `SuiteResult.minimum_score_metrics`.
Sparse informational means and intervals use only applicable case-runs.

`SuiteResult.intervals` and `gate_intervals` use deterministic 95% percentile bootstrap
intervals (2,000 draws, seed 42). Each draw samples cases, then repeats within those cases;
repeats are not independent cases. Small cohorts and synthetic data limit inference.
`paired_difference_intervals(baseline, candidate)` estimates paired changes and rejects
different case/repeat cohorts or metric applicability.

`assign_splits` ranks machine IDs by a hash with fixed salt
`cs-platform-eval-split-v1` and assigns approximately 2:1 train/test within categories
(four machines give three train, one test). It never uses Python's randomized hash.
Manifest regeneration must retain existing explicit splits: those assignments are frozen
when appending cases, even across categories. Conflicting machine assignments are rejected.
Shared-machine constraints or a singleton stratum can prevent balancing; warnings identify
strata without both splits.

The CLI always writes private JSONL results, a run summary, per-case-run transcripts and
escaped static HTML, by default under gitignored `.eval-results/`. Summaries include
category/split means, CIs, error classes and saturation/threshold-margin warnings.
Agent and harness revisions are independent; `--agent-revision` records a pinned baseline
agent while the harness changes. Hosted tool traces are resolved only through the exact
response-bound episode; unavailable or storage-truncated traces are explicitly incomplete.
Local `--episodes-output` exports an explicitly `real` JSONL population, including failed
attempts, and rejects hosted use or an existing destination.
All result, summary, HTML, transcript and episode-export destinations must be distinct
and unused before model calls. Writers exclusively create files and transcript directories.

Predeclare a primary metric and practical noninferiority margins for the other gated
metrics before measuring. Keep a change only if the primary metric's paired improvement
CI lies above zero on both train and test, other gated metrics are noninferior within
those margins, and every unchanged threshold passes. Saturated metrics require
noninferiority, not impossible strict improvement. Tune from train transcripts only.
Do not inspect test transcripts while tuning, rerun until green, or infer improvement from
overlapping/unpaired confidence intervals. Serialize live measurements; offline tests
are not evidence of live quality. The unchanged-agent 18-case × 3-repeat baseline
[failed and was retained](../../docs/iteration-3/q2.md), not rerun to seek a pass.
See the [eval guide](../../evals/rca/README.md) for paired comparison commands.

Local startup creates a real episode span, enables HTTP propagation when exporting,
and flushes owned exporters on exit. Streaming context is attached per iterator pull;
hosted telemetry stays owned by the hosting library. See [trace continuity](../../docs/tracing.md)
for sampling, query templates, historical evidence and the unverified managed MCP boundary.

## Hosted response identity

The installed `agent-framework-foundry-hosting` adapter (`1.0.0b261015`) does not
project `AgentResponse.additional_properties["episode_id"]` into Responses metadata.
Its public `prepare_options` hook does expose `HostedResponseRequest.response_id`.
The hosted entry point uses `prepare_episode_options` to pass that trusted ID in
per-run options. Capture removes it before the model or tools run.

A hosted episode records `hosted_response_id` and uses `hosted_episode_id(response_id)`
as its point-read key: UUID5 with `NAMESPACE_OID` and
`cs-platform:hosted-response:<response_id>`. The host and CLI share this mapping.
Deploy both the updated agent and `platform-api` for this contract: the API packages
its own `cs-platform`. An older API's `Episode` model silently drops
`hosted_response_id` when reading Cosmos DB, leaving new episodes unverifiable even
when the updated agent recorded the field correctly.
Neither incident text, creation time nor session affinity determines identity.
Failed runs retain the same binding when execution reaches capture. A failure before
agent execution, a process crash or a store outage may leave no episode.

`RunOutput` carries both IDs, including terminal hosted failures. The CLI retries
only the API's exact episode-not-found response, at most five point reads with
half-second intervals, and verifies both stored IDs before claiming a match.
Missing records, missing identifiers and API
failures are reported explicitly, without falling back to recent-episode listings.
Route/configuration 404s, credential/key acquisition failures and invalid episode
payloads leave the identity explicitly unverified rather than claiming delayed
persistence. Failed responses without tool details report calls as unavailable.
Legacy episodes keep their existing IDs and default `hosted_response_id` to `None`;
local runs still receive a random episode ID. The agent report schema is unchanged.

Offline tests exercise the real adapter and OpenAI client, including concurrent
identical inputs in one hosting session, out-of-order completion, streamed and failed
responses, and delayed persistence. On 2026-10-29, one successful hosted diagnosis
against the combined iteration 2 release verified the gateway behavior: the real CLI
printed the exact response binding, both IDs matched the stored episode through the
API, and `csai episodes show <episode-id>` displayed the same Response ID. The episode
contained eight tool calls. No live failure was forced; failed protocol responses
remain covered offline. Repeat the hosted check when upgrading the hosting adapter.

Shared local validation ran three full 18-case suites at concurrency one: all 54
runs completed on their first attempt. All unchanged quality thresholds passed on
replay with the arithmetic-only mean-aggregation fix in
[PR #4](https://github.com/marcgs/cs-ai-platform-sample/pull/4). The third run's exact
tool coverage was 81/90; naive float summation had incorrectly put it below 0.90.
The replay changed no per-case score or threshold and made no additional model calls.

## Tests

`tests/conftest.py` provides `ScriptedChatClient`, a chat client that returns scripted model turns while Agent Framework's real tool-invocation loop runs the tools. The capture tests cover streaming and non-streaming runs, tool failures, model failures, invalid structured output and store outages, all without Azure.
