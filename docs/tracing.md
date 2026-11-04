# Tracing

Every agent run produces an OpenTelemetry trace in Application Insights, and its episode records the trace ID, so you can go from an episode to its spans.

## How it works

- **Hosted agent:** Foundry's hosting library owns telemetry: it sets up the exporter, sampling and shutdown. The agent doesn't initialize a second provider.
- **Local runs** (`rca-local`): the platform's telemetry bootstrap (`cs_platform.telemetry`) sets up the Azure Monitor exporter when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, and flushes before exit. Without a connection string, spans have valid IDs but aren't exported.
- **The episode span:** the capture middleware starts a `cs_platform.episode` span and takes the episode's trace ID from it. It parents Agent Framework's `invoke_agent`, model and tool spans, including for streamed runs and failed runs. New spans carry `cs_platform.episode_id` as an attribute.
- **Sampling:** local runs default to `parentbased_always_on` (keep every new trace, respect an upstream decision); an explicit `OTEL_TRACES_SAMPLER` wins. Hosted sampling is the hosting library's configuration. The Functions host uses adaptive sampling with requests excluded.

## Find an episode's trace

In the Log Analytics workspace, paste the episode's `trace_id` (`csai episodes show <id>` prints it):

```kusto
union AppRequests, AppDependencies
| where TimeGenerated > ago(3d)
| where OperationId == "<episode trace_id>"
| project TimeGenerated, Type, Name, Id, ParentId, DurationMs, Properties, ItemCount
| order by TimeGenerated asc
```

`Id` is the span ID, `ParentId` its parent and `OperationId` the trace ID. Initialization and tool discovery can happen before the episode span, so they may be missing from its graph.

## Known limitation

The trace stops at the toolbox: the tool server's (Azure Functions) spans don't join the agent's trace, although Agent Framework sends the trace context with each MCP request. See [Foundry findings](foundry-findings.md#traces-stop-at-the-toolbox). To check whether that has changed:

```kusto
let agents = union AppRequests, AppDependencies
    | where TimeGenerated > ago(2d) and Name startswith "invoke_agent"
    | distinct OperationId;
AppRequests
| where TimeGenerated > ago(2d) and Name == "get_machine_context"
| summarize handlerRows=count(), joinedRows=countif(OperationId in (agents))
```

`joinedRows` above zero means tool handler spans now join agent traces.

References: [Functions OpenTelemetry configuration](https://learn.microsoft.com/azure/azure-functions/opentelemetry-howto) · [MCP tool trigger](https://learn.microsoft.com/azure/azure-functions/functions-bindings-mcp-tool-trigger)
