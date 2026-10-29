# A6: toolbox latency

## Status

**Investigation deliverable complete; no performance improvement is claimed.**
The baseline, repeatable authenticated probe, same-invocation attribution and
supported-remedy investigation are verified below. No safe supported runtime
remedy was found in the installed SDK or the current stable release. No
performance change or Azure write was made.

A3's verified trace path is needed before attributing time to the managed toolbox,
Functions startup, MCP session setup or the tool handler. The combined release's
same-invocation spans now demonstrate client-side queueing and separate model/RPC
time, but not handler or managed-service internals. This is a documented SDK and
observability limitation, not an unexplained claim of a fix. The post-release
measurements below are new baselines, not an A6 improvement.

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
boundaries; their difference is not proven model or toolbox time. This smoke
does not provide a verified model/tool critical-path breakdown; the combined
trace below does. This smoke used a
diagnosis tool mix, not the probe's identical-argument single-tool workload.

## Combined-release baseline and causal span evidence

The approved, unmerged integration snapshot
`4afdaa4d2f923c2ac0d66aea9779a1091f13bbbb` was deployed separately. A4 performed one
hosted correlation check, then handed the slot to A6. The same model-free
single-session probe ran after that check, using A5's verified fresh environment
with values **overwriting** inherited settings. The old root environment was not
used. Eight remote calls validated and matched the seed; all phases had zero errors.

| Path / phase | Successful / attempted | Min (s) | Median (s) | Nearest-rank p95 / max (s) |
|---|---:|---:|---:|---:|
| Toolbox initialization | 1 / 1 | 2.395 | 2.395 | 2.395 |
| Toolbox first call | 1 / 1 | 0.661 | 0.661 | 0.661 |
| Toolbox reused-session calls | 3 / 3 | 0.596 | 0.695 | 0.713 |
| Toolbox close | 1 / 1 | 0.001 | 0.001 | 0.001 |
| Direct MCP initialization | 1 / 1 | 0.797 | 0.797 | 0.797 |
| Direct MCP first call | 1 / 1 | 0.204 | 0.204 | 0.204 |
| Direct MCP reused-session calls | 3 / 3 | 0.207 | 0.213 | 0.295 |
| Direct MCP close | 1 / 1 | 2.811 | 2.811 | 2.811 |
| In-process first call | 1 / 1 | 0.000089 | 0.000089 | 0.000089 |
| In-process subsequent calls | 3 / 3 | 0.000035 | 0.000043 | 0.000045 |

This is another deployment/warmup-conditioned baseline, not a controlled A6 fix.
The numerical objective alone is not sufficient for acceptance.

### Same-invocation critical path

A3 queried A4's exact hosted trace, not another diagnosis: 33 retained spans, all
with `ItemCount=1`, including the episode and framework agent parent/child link,
four model spans and eight MCP RPC spans. Every RPC's exact parent is the
corresponding `execute_tool` span. The handler join still has zero Function spans.

Using each span's timestamp and duration, merge overlapping intervals before
calculating elapsed time. The nested hosted model span must not be added again:

| Same-invocation measurement | Elapsed (s) |
|---|---:|
| A4 request-to-response wall interval | 68.753 |
| Stored episode interval | 42.905 |
| Episode trace span, including persistence | 43.680 |
| Model-call span interval union: four spans, three disjoint intervals | 8.947 |
| MCP RPC interval union: eight serial spans | 33.930 |
| Model-or-RPC interval union | 42.877 |
| Episode-span time outside those intervals, unclassified | 0.803 |

These are measured envelopes, not pure model compute or tool-handler time. RPC
duration includes the client/network/service boundary. The 0.803 s remainder is
not attributed exclusively to storage. The broader CLI/request, stored episode
and episode-span boundaries differ; do not infer a cause from their differences.

### Observed cause of inflated per-tool durations: client queueing

In each four-call batch, `execute_tool` wrappers start within about 4 ms of one
another, but their child `tools/call` RPCs are serial, with no adjacent overlap
at 5 ms tolerance. A3 independently verified the parent IDs and interval ordering.
The wrapper includes time waiting before the RPC:

| Four-call batch | Pre-RPC wait min / median / max (s) | RPC min / median / max (s) |
|---|---:|---:|
| First | 0.001 / 9.019 / 12.096 | 0.288 / 3.670 / 6.230 |
| Second | 0.001 / 8.429 / 14.164 | 2.873 / 5.643 / 5.914 |

This is same-invocation, parent/child evidence of queueing, unlike subtraction of
unrelated requests. It explains why a captured tool duration can reach about
20 s although its own RPC lasts about 6 s. Do not sum overlapping wrappers.

The installed `agent-framework-core` **1.22.0** implementation explains this
serialization: `FoundryToolbox` supplies a header provider, and
`MCPStreamableHTTPTool.call_tool` holds `_call_headers_lock` across the awaited
RPC when a provider exists. That lock protects session/header identity, not just
connection creation. Existing connection reuse does not remove this queue.

No lock bypass or concurrent-client pool was added. Preserving authentication
identity isolation is mandatory, and neither a safe alternate lifecycle nor its
before/after performance has been verified. A separate bounded experiment would
need explicit concurrency authorization and must account for additional
initialization/session cost. The remaining multi-second RPC time is still not
localized within the client/network/toolbox/Functions boundary; a missing handler
join is not proof of proxy or cold-start delay. No always-ready proposal follows.

Adding a changing `traceparent` through the public header provider is not a safe
shortcut: the SDK includes every header name/value in its session identity, and
an identity change reconnects the session. That would alter the very lifecycle
being measured. A3 also verified that the MCP writer task need not retain the
episode's current context. Use the existing operation-boundary W3C `_meta`
propagation for investigation; supported per-call header context needs upstream
coordination, not an authentication-lock bypass.

### Supported-remedy investigation

The public constructors and lifecycle implementations were inspected on
2026-10-29. The latest stable upstream Python release was **1.23.0**, published
2026-10-22; the installed version is **1.22.0**. The stable release still holds
the identity lock across the RPC, and its `FoundryToolbox` still always supplies
the provider:

- [Stable release](https://github.com/microsoft/agent-framework/releases/tag/python-1.23.0)
- [Authenticated call lock, release-tagged source](https://github.com/microsoft/agent-framework/blob/python-1.23.0/python/packages/core/agent_framework/_mcp.py#L4526-L4564)
- [Toolbox constructor, release-tagged source](https://github.com/microsoft/agent-framework/blob/python-1.23.0/python/packages/foundry_hosting/agent_framework_foundry_hosting/_toolbox.py#L215-L295)

The upstream main branch was also checked and retained this guard. No dependency
upgrade was applied: upgrading solely to 1.23.0 would not remove the observed
serialization, and unrelated dependency changes are not a measured remedy.

| Supported option inspected | Verified constraint |
|---|---|
| Reuse one client/session | Already measured; one initialization serves multiple warm calls. The identity lock still encloses every RPC. |
| HTTP client, transport or connection limits | The lock is acquired before the base RPC call. Increasing HTTP capacity cannot admit another guarded call. |
| Caller-supplied MCP session | The guard remains; unknown or changed header identity is rejected rather than silently reused. |
| `static_headers` / caller `header_provider` | The toolbox still adds its platform provider. Changing headers can reconnect; removing the provider would bypass platform identity handling, not tune a supported concurrency setting. |
| `load_prompts`, `load_tools`, progressive discovery | Discovery/lifecycle settings do not change the guarded RPC path. Prompts are already disabled; removing discovery would not preserve the agent's existing tool contract. |
| Timeout, task and close options | These control deadlines, task handling or teardown, not parallel admission. Skipping session termination is not a queueing fix. |
| Model parallel-call option | It changes tool scheduling, not the SDK lock. Serial wrappers could look faster individually without improving diagnosis wall time. |
| Latest stable SDK | 1.23.0 retains both the guard and mandatory toolbox provider. No supported concurrent same-identity fast path was found in these public interfaces. |

This is deliberately scoped to verified versions and interfaces, not a claim that
no future upstream solution is possible. A pool, private-state override or raw
transport replacement was not implemented: none is a minimal, verified remedy
preserving all existing platform identity and session semantics.

### Offline causal reproduction and safeguard checks

An isolated experiment used the **real public `MCPStreamableHTTPTool`**, its
`header_provider` and `http_client` parameters, and an authenticated synthetic MCP
server over `httpx.MockTransport`. No SDK methods or private state were patched.
There were no sockets, model requests or Azure calls.

Four simultaneously scheduled calls with identical caller identity and a 40 ms
synthetic handler delay took **0.167 s** wall time. Maximum server concurrency
was **1**, with exactly **one initialization**. Thus serialization persists with
session reuse and without a slow network or managed service.

The synthetic server bound each session ID to its authenticated principal and
rejected an unauthorized request with HTTP **401**. Three sequential principal
changes returned the correct principal each time and caused three terminations
and reinitializations; final close left no live sessions. A queued cancellation
propagated, never reached the server, and left the same session usable for the
next call. These checks reproduce the guard's purpose, not just its cost.
No replacement cancellation or authorization implementation was introduced.

The experiment's source and machine-readable result remain in ignored
`.azure/a6-sdk-repro.py` and `.azure/a6-sdk-offline-repro.json`. Upstream version,
source hashes and public-interface observations are in
`.azure/a6-upstream-options.json`. The live, developer-facing reproduction remains
the checked-in command below; no framework-behavior regression tests were added
to the product suite.

**Concrete outcome:** inflated wrapper durations include verified SDK queueing.
Current supported toolbox/session APIs preserve this serialization to protect
identity. The remaining RPC envelope cannot be separated into network, managed
toolbox and handler time with the deployed trace path; A3 verified client `_meta`
propagation offline but found no documented managed forwarding switch or same-call
handler join. This is the boundary of the investigation, not evidence that
Functions cold starts or the proxy caused every slow RPC. No cache, pool,
authentication bypass or infrastructure change is justified by these results.

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

For a separately staged release, use its approved azd project and refresh inherited
environment values from its verified private handoff. Process values override azd
values: merely changing `--azd-project` does not replace stale exported endpoints.
Never use `setdefault` to load a newer deployment's environment.

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
Combined-release artifacts are `a6-combined-baseline.json`,
`a6-combined-hosted-trace.json` and `a6-combined-critical-path.json`. The latter two
derive from A3's private same-invocation handoff; no extra model run was made.

## Trace attribution and future optimization work

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
The combined hosted analysis above instead uses A4's already correlated invocation.

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
5. The post-A5 and combined-release baselines and same-invocation model/RPC
   interval breakdown are captured above. Preserve the client queue/RPC/handler
   distinction in any follow-up; no heavy eval suite is needed solely for A6.

Offline verification: full ruff, formatting, pyright and pytest (115 tests).
Seven focused tests cover payload normalization, protocol/domain errors, session
reuse, failure accounting, teardown and successful-sample distributions.
No live agent eval was run by A6: this adds measurement tooling, not agent
instructions, schemas, tools, capture or eval data. Client queueing, its supported
SDK limitation and the hosted model/RPC critical path are verified. No runtime
remedy or controlled improvement is claimed. Future optimization needs a supported
identity-safe SDK change and a separately authorized controlled comparison;
managed toolbox-to-handler propagation and per-RPC internal localization remain
unproven. They are documented investigation limits, not invented causal findings.
