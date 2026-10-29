# A6: toolbox latency

## Status

Baseline and a repeatable, model-free probe are available. **Acceptance is pending.**
No performance change or Azure write was made. Connection reuse is already present
in the measured warm calls, so adding a cache is not a justified remedy.

A3's verified trace path is needed before attributing time to the managed toolbox,
Functions startup, MCP session setup or the tool handler. A controlled causal
comparison remains outstanding. The post-A5 baseline and hosted smoke below
provide separately labeled new measurements, not an A6 improvement.

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

## Post-A5 baseline, not an A6 after-fix result

After A5's approved pinned-main release and its successful hosted smoke, the same
checked-in command ran with `--warm-calls 3 --sessions 1`, same machine, tool,
arguments, region, path order and client/session reuse. No A6 performance change
was made. Every remote payload validated and matched the local seed: **8 / 8**,
with zero initialization, call or teardown errors.

| Path / phase | Successful / attempted | Min (s) | Median (s) | Nearest-rank p95 / max (s) |
|---|---:|---:|---:|---:|
| Toolbox initialization | 1 / 1 | 2.106 | 2.106 | 2.106 |
| Toolbox first call | 1 / 1 | 0.682 | 0.682 | 0.682 |
| Toolbox reused-session calls | 3 / 3 | 0.559 | 0.576 | 0.763 |
| Toolbox close | 1 / 1 | 0.001 | 0.001 | 0.001 |
| Direct MCP initialization | 1 / 1 | 0.892 | 0.892 | 0.892 |
| Direct MCP first call | 1 / 1 | 0.587 | 0.587 | 0.587 |
| Direct MCP reused-session calls | 3 / 3 | 0.185 | 2.836 | 2.836 |
| Direct MCP close | 1 / 1 | 2.475 | 2.475 | 2.475 |
| In-process first call | 1 / 1 | 0.000099 | 0.000099 | 0.000099 |
| In-process subsequent calls | 3 / 3 | 0.000036 | 0.000040 | 0.000045 |

This deployment and the preceding hosted smoke change the conditions, including
possible server warmup. The lower toolbox median satisfies only the numerical
part of the provisional objective. It is not a controlled A6 intervention, uses
one session rather than three per arm, and does not establish a remedy or cause.
Direct network calls still vary substantially despite session reuse.

### A5's single hosted diagnosis

A5 supplied its one authorized smoke measurement, from the new deployment:
**70.032 s CLI wall time**, **41.101 s stored episode interval**. All nine complete
tool payloads matched deterministic seed JSON, totaling **22,241 bytes**, within
the episode size budget and with all truncation flags false. Model usage was
10,345 input / 1,377 output tokens.

| Captured tool | Calls | Min (s) | Median (s) | Max (s) |
|---|---:|---:|---:|---:|
| Machine context | 1 | 5.538 | 5.538 | 5.538 |
| Error events | 1 | 11.150 | 11.150 | 11.150 |
| Logbook | 1 | 13.608 | 13.608 | 13.608 |
| Error-code lookup | 3 | 0.273 | 5.914 | 6.216 |
| Telemetry window | 3 | 6.421 | 12.176 | 17.650 |

These are episode capture durations, not separately measured handler or transport
spans. Calls may overlap: **do not sum them or subtract them from either total**
to claim model latency. CLI wall time and the episode interval have different
boundaries; their difference is not proven model or toolbox time. A verified
model/tool critical-path breakdown remains outstanding. This smoke used a
diagnosis tool mix, not the probe's identical-argument single-tool workload.

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
The separate post-release probe is `a6-post-a5-baseline.json`. A5 retains its
hosted smoke and release inventory in its own ignored `.azure/a5-private/`.

## Trace attribution and remaining work

A3's read-only investigation found **zero same-operation joins** between retained
`invoke_agent rca-agent` dependencies and `get_machine_context` requests over two
days. Agent/model spans share an operation, while Function root spans exist
separately. This is a verified correlation gap, not evidence that the toolbox
spent the difference in time. Those retained traces are not the baseline probe's
invocations. Sampling also limits conclusions from missing records.

A broader A3 query on 2026-10-29 checked agent roots in both request and dependency
tables, including versioned names:

```kusto
let agents = union AppRequests, AppDependencies
    | where TimeGenerated > ago(2d) and Name startswith "invoke_agent"
    | distinct OperationId;
AppRequests
| where TimeGenerated > ago(2d) and Name == "get_machine_context"
| summarize handlerRows=count(), handlerOperations=dcount(OperationId),
    joinedRows=countif(OperationId in (agents))
```

Result: **159 handler rows, 159 handler operations, zero joined rows**. Exact
`invoke_agent rca-agent` dependency roots numbered 81 rows / 81 operations;
versioned dependency roots numbered 299 rows / 80 operations. Agent request
roots numbered 82 rows / 82 operations. These retained-record counts are not
latency sample sizes.

One retained successful agent/toolbox graph had 38 spans, including `execute_tool`
and `tools/call diagnostics___get_machine_context`, but no handler spans. To inspect
one graph, use its private operation ID rather than matching unrelated timestamps:

```kusto
union AppRequests, AppDependencies
| where OperationId == "<trace-id>"
| project TimeGenerated, Type, Name, Id, ParentId, DurationMs
```

The installed Agent Framework injects W3C trace keys into MCP request `_meta`.
Functions exposes its trigger payload through `MCPToolContext`, but whether the
managed toolbox forwards those keys remains unproven. This identifies where to
verify propagation; it does not locate the observed seconds of delay.

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
5. The separately labeled post-A5 baseline and single hosted smoke are captured
   above. Obtain the verified model/tool critical-path breakdown from correlated
   spans; do not run a heavy eval suite solely for this task.

Offline verification: full ruff, formatting, pyright and pytest (115 tests).
Seven focused tests cover payload normalization, protocol/domain errors, session
reuse, failure accounting, teardown and successful-sample distributions.
No live agent eval was run: this adds measurement tooling, not agent instructions,
schemas, tools, capture or eval data. Full A6 acceptance remains blocked on the
causal trace attribution, controlled comparison or verified service limitation,
and model/tool critical-path evidence above.
