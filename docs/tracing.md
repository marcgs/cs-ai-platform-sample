# Trace continuity (A3)

## Local runs

`rca-local`, `csai diagnose --target local` and `csai eval --target local` initialize
telemetry before building an agent. The platform middleware starts a real
`cs_platform.episode` span before reading its trace context. The episode's trace ID
comes from that span, not from a generated correlation string.

The episode span parents Agent Framework's `invoke_agent`, model and tool spans.
Streaming runs attach its context around each iterator pull, including when a
different task consumes the stream. The span ends after stream finalization or
cleanup. Failed runs and recovered tool failures retain their trace context.
The middleware also works with a provider installed by an embedding application.

With `APPLICATIONINSIGHTS_CONNECTION_STRING`, the Microsoft distro exports local
telemetry and enables HTTPX instrumentation, which is disabled by default in the
installed distro. This injects W3C context into outgoing HTTP requests. Without a
connection string, an SDK provider still supplies valid local context, but no
exporter is installed: an ID alone does not mean a trace can be queried in Azure.

The CLI flushes its owned trace, log and metric providers before exiting and
registers an exit fallback. It never flushes or replaces a provider owned by a host.
Foundry's hosting library remains responsible for hosted export and shutdown;
the hosted entry point does not call the local bootstrap.

## Sampling

For this low-volume sample, local bootstrap defaults `OTEL_TRACES_SAMPLER` to
`parentbased_always_on`: retain every new root trace, but respect an upstream
sampling decision. An explicit setting wins, including `always_off`. This costs
more ingestion and storage than probabilistic sampling, especially during evals.
Prompt/response recording is not enabled by this change.

Hosted sampling remains hosting-library configuration. For a coordinated live
trace investigation, configure the same parent-based sampler through the
supported hosting environment and verify it after deployment. Do not initialize
a second provider inside the hosted agent.

The Functions host currently has adaptive Application Insights sampling enabled,
with requests excluded. Its sampling and the managed toolbox can still leave
partial graphs even when local roots are retained. This PR does not change those
deployed settings. A valid unsampled context is not evidence of exported spans.

## Read-only investigation, 2026-10-29

The observed historical gap is **not reproducible in the retained episodes now**:

- The API returned 81 episodes, each with a valid 32-character trace ID.
- Exact trace-ID lookup found request/dependency rows for all 81: 58 episodes
  from October 28 and 23 from October 29. This establishes presence, not completeness.
- Workspace retention was 30 days and Application Insights retention 90 days.
  These current settings do not explain a one-day-old gap.
- Retained October 28 request/dependency ingestion delays had maxima of about
  193/73 seconds. They do not establish when the original unsuccessful lookup ran.
- Some retained October 27 model dependency rows had `ItemCount > 1`; the
  October 28 snapshot had no weighted request/dependency rows. Sampling occurred,
  but there is no evidence that it caused the earlier observation.
- Resource-group deployment history retained 17 entries; the queried activity
  table had no relevant deployment records. Resource provisioning history does
  not establish which exporter configuration a particular hosted container used.

The original query scope, observation time and container-level exporter state
were not preserved with the earlier observation. Its historical cause therefore
cannot be established. Do not label it an exporter failure, retention expiry,
sampling loss or ingestion delay without more evidence. No unexported history
has been recovered.

## MCP boundary and A6 handoff

The same retained two-day snapshot contained 159 `get_machine_context` handler
requests in 159 operations. **None** shared an operation with any `invoke_agent`
root. Agent-side evidence included 81 framework invocation spans, 299 versioned
invocation rows across 80 operations, and 82 hosting invocation requests.
A successful 38-span agent graph included `execute_tool` and
`tools/call diagnostics___get_machine_context`, but no function-handler span.

The installed Agent Framework injects W3C keys into MCP request `_meta`.
The Functions Python SDK exposes an `MCPToolContext` trigger payload, but that
does not prove the managed toolbox forwards the original metadata or HTTP trace
headers to the function. The existing Functions host already instruments handler
requests. No unsupported model-argument correlation or replacement Functions
telemetry pipeline has been added.

The local HTTP propagation path is covered offline with a real instrumented
HTTPX client, an in-memory exporter and a simulated server extracting W3C headers.
It is **not** a deployed toolbox-to-Functions propagation proof. That managed hop
remains an explicit live-verification blocker; no feature deployment was authorized.
The current data does not localize latency inside that boundary.

For A6, `tools/call` is the client RPC duration, `execute_tool` includes framework
execution, and a Functions handler request measures a different server interval.
Do not subtract unrelated operations or sum overlapping/parallel tool spans.
Initialization and tool discovery can precede an episode's span; their absence
from an episode graph does not mean they took no time.

## Query templates

In the Log Analytics workspace, paste an episode's `trace_id` into this query.
`Id` is the span ID, `ParentId` its parent and `OperationId` the trace ID.

```kusto
union AppRequests, AppDependencies
| where TimeGenerated > ago(3d)
| where OperationId == "<episode trace_id>"
| project TimeGenerated, Type, Name, Id, ParentId, DurationMs, Properties, ItemCount
| order by TimeGenerated asc
```

New platform spans carry `Properties["cs_platform.episode_id"]`. Older hosted
spans need not have this attribute; use the episode's exact trace ID instead.
Application Insights' legacy tables use `requests`/`dependencies`,
`operation_Id`, `id`, `operation_ParentId`, `duration` and `customDimensions`.

Repeat the managed-boundary check with the same bounded time window on both sides:

```kusto
let agents = union AppRequests, AppDependencies
    | where TimeGenerated > ago(2d) and Name startswith "invoke_agent"
    | distinct OperationId;
AppRequests
| where TimeGenerated > ago(2d) and Name == "get_machine_context"
| summarize handlerRows=count(), handlerOperations=dcount(OperationId),
    joinedRows=countif(OperationId in (agents))
```

For historical evidence, join exact episode trace IDs to distinct `OperationId`
values, not input text or approximate timestamps. Inspect `ItemCount` and
`ingestion_time() - TimeGenerated` separately from trace presence.

## Verification still required

Offline gates and in-memory exporter tests pass. No model calls or Azure writes
were made for A3. The Azure-backed local eval, a fresh local exported diagnosis,
and a fresh hosted diagnosis with this middleware remain pending. A coordinated
feature deployment must precede hosted acceptance. Verify the episode/trace
match and one real diagnostic MCP parent chain; if the managed service strips
context, retain the boundary limitation and obtain service-side evidence.

References: [Functions OpenTelemetry configuration](https://learn.microsoft.com/azure/azure-functions/opentelemetry-howto)
and [MCP tool trigger](https://learn.microsoft.com/azure/azure-functions/functions-bindings-mcp-tool-trigger).
