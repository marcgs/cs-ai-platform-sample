# A6: toolbox latency

## Status

Baseline and a repeatable, model-free probe are available. **Acceptance is pending.**
No performance change or Azure write was made. Connection reuse is already present
in the measured warm calls, so adding a cache is not a justified remedy.

A3's verified trace path is needed before attributing time to the managed toolbox,
Functions startup, MCP session setup or the tool handler. A controlled repeat and
whole-diagnosis measurement remain outstanding. A5's release changes the baseline:
do not describe a comparison across that deployment as an A6 improvement.

## Unchanged baseline

Captured on 2026-10-29 before A5, with measuring checkout revision `85a1e4d`, using
the existing active deployment, region, toolbox version and synthetic dataset.
That checkout revision is not a verified deployed-source revision: the deployed
agent predates the review fixes. A5 owns the private release/rollback inventory.
The probe ran on one developer machine, concurrency **1**, with no model requests. The same
`get_machine_context(machine_id="M-0007")` was used on all paths. The toolbox tool
has its server prefix; direct MCP has the unprefixed name.

One client/session per path was opened, then reused for one first and three warm
calls. Paths ran sequentially, toolbox before direct. **First does not mean cold:**
there is no evidence that the server instance was cold, and the previous idle time
is unknown. HTTP clients and MCP sessions were not recreated between warm calls.
Initialization includes authentication, MCP initialization and tool discovery.
Local execution includes JSON serialization, but excludes seed loading.

| Path / phase | Successful / attempted | Min (s) | Median (s) | Nearest-rank p95 / max (s) |
|---|---:|---:|---:|---:|
| Toolbox initialization | 1 / 1 | 10.660 | 10.660 | 10.660 |
| Toolbox first call | 1 / 1 | 6.197 | 6.197 | 6.197 |
| Toolbox reused-session calls | 3 / 3 | 3.180 | 5.811 | 6.728 |
| Direct MCP initialization | 1 / 1 | 3.552 | 3.552 | 3.552 |
| Direct MCP first call | 1 / 1 | 2.858 | 2.858 | 2.858 |
| Direct MCP reused-session calls | 3 / 3 | 0.175 | 2.774 | 2.942 |
| In-process first call | 1 / 1 | 0.000295 | 0.000295 | 0.000295 |
| In-process subsequent calls | 3 / 3 | 0.000029 | 0.000035 | 0.000043 |

These are descriptive small-sample statistics, not reliable tail estimates.
Successful here means no transport exception. The original timing probe stored SDK
content object representations, not decoded payloads; its hashes are **not**
correctness evidence. A separate unchanged-deployment check below verifies payloads.

An earlier direct initialization attempt returned HTTP 401 after 2.731 s. The
scratch probe used the unsupported `headers` keyword rather than `static_headers`,
so it did not send the existing MCP system key. This failed attempt is not included
in successful direct timings. Correcting the probe required no authentication or
service configuration change. The original toolbox cleanup also emitted an SDK
cleanup warning; it did not invalidate the completed call durations.

### Correctness check, still unchanged

The repeatable command below was then run with `--warm-calls 0`, before A5.
Both remote payloads validated against `MachineContext`; canonical JSON hashes
matched the local seed. Initialization, calls and close all had **0 errors**.

| Path / phase | Successful / attempted | Median (s) |
|---|---:|---:|
| Toolbox initialization | 1 / 1 | 2.465 |
| Toolbox first call | 1 / 1 | 0.674 |
| Toolbox close | 1 / 1 | 0.001 |
| Direct initialization | 1 / 1 | 8.842 |
| Direct first call | 1 / 1 | 3.022 |
| Direct close | 1 / 1 | 2.396 |
| In-process first call | 1 / 1 | 0.000109 |

This is **not an after-fix result**: nothing was tuned. The much faster toolbox
call and slower direct initialization demonstrate variability even without a
deployment. A 50 ms local-tool figure is not a network baseline. Nor can timing
differences between these sequential runs locate a proxy or cold-start delay.
The earlier roughly one-minute diagnosis estimate was not remeasured; these
model-free calls must not be reported as whole-diagnosis latency.

## Numerical objective, recorded before tuning

If a cause is verified and a remedy is approved, repeat the same arguments,
environment and client lifecycle with concurrency 1. Target a **50% reduction**
from the initial warm toolbox median (5.811 s), hence **median <= 2.905 s**,
with **p95 <= 6.728 s**, zero protocol/domain/payload errors, and identical
validated payloads. Treat this as a provisional objective, not a passed gate:
use at least three independently initialized sessions in each arm, retain the
first/warm split, and check stability/order effects before claiming improvement.
Hold other workstreams fixed; record any deployment as a new baseline.

The single 0.674 s check does not satisfy this objective. It is not a warm sample,
not an intervention, and not a controlled comparison.

## Repeat the comparison

Use the isolated workspace's dependencies and an existing signed-in azd
environment. This command makes no model calls and performs no deployment,
role assignment or configuration change:

```bash
uv run python -m csai.latency \
  --azd-project . \
  --warm-calls 3 --sessions 1 \
  --output .azure/a6-latency.json
```

In a worktree without its own azd environment, set `--azd-project` to the existing
project directory. This is a read-only environment lookup. Direct MCP access must
already be authorized: the command reads the existing `mcp_extension` system key
via ARM `listkeys` (a read operation with a POST verb) and sends `x-functions-key`.
The toolbox uses an Entra credential. Neither credential is persisted. Do not
disable authentication to obtain a measurement.

Use `--direct-first` to reverse path order in a separate coordinated run, and
`--sessions 3` only when the shared measurement slot permits it. The CLI caps
session/sample counts and always runs sequentially. The default makes eight
remote tool calls. No automatic application retry masks errors; underlying
service/SDK retries are not separately instrumented.

The artifact includes UTC call windows, revision, dependency versions, selected
environment metadata, canonical result hashes, elapsed time, phase, session and
exception class. It is incrementally persisted after each sample. Output must
be gitignored; do not attach the raw artifact to a public PR. The terminal prints
only aggregate timings, counts and errors. A failed initialization, call, schema
check, payload comparison or close causes a nonzero exit.

The original raw artifacts remain in the measuring worktree's ignored `.azure/`:
`a6-baseline.json`, `a6-direct-baseline.json` and `a6-correctness-baseline.json`.
They retain exact private timing windows/configuration for trace investigation.
The first two used a scratch probe; only the last uses the checked-in command.

## Trace attribution and remaining work

A3's read-only investigation found **zero same-operation joins** between retained
`invoke_agent rca-agent` dependencies and `get_machine_context` requests over two
days. Agent/model spans share an operation, while Function root spans exist
separately. This is a verified correlation gap, not evidence that the toolbox
spent the difference in time. Those retained traces are not the baseline probe's
invocations. Sampling also limits conclusions from missing records.

The probe does not currently inject a traceparent or export a client span; UTC
windows alone cannot establish causal parentage. A later trace-enabled comparison
must use A3's verified propagation path without silently changing session reuse.

1. Use A3's verified trace queries and join MCP handler spans to the **same**
   measured invocation. Initialization/client timing alone cannot separate TLS,
   authentication, proxy queues, Functions startup and MCP server execution.
2. Record whether traceparent reaches the managed boundary and whether the
   downstream spans are available. Missing spans are not proof that the proxy
   caused the delay.
3. If verified spans identify an actionable cause, change only that cause and
   rerun the comparison with all other versions held fixed. No always-ready
   capacity is proposed without cold-start evidence, current Flex Consumption
   support verification and ongoing cost analysis.
4. If the time is inside an unobservable/uncontrollable managed boundary,
   document that specific evidence and limitation instead of claiming a fix.
5. After A5, capture a separately labeled baseline and a serialized, low-cost
   whole-diagnosis sample with model/tool/total durations. Do not run a heavy eval
   suite solely for this task.

Offline verification: full ruff, formatting, pyright and pytest (115 tests).
Seven focused tests cover payload normalization, protocol/domain errors, session
reuse, failure accounting, teardown and successful-sample distributions.
No live agent eval was run: this adds measurement tooling, not agent instructions,
schemas, tools, capture or eval data. Full A6 acceptance remains blocked on the
trace attribution and controlled/live end-to-end evidence above.
