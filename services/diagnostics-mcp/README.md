# Diagnostics MCP server

Read-only diagnostic tools over the synthetic fleet, exposed as a remote **MCP server** with the Azure Functions MCP extension. Agents reach it through a Foundry toolbox; any MCP client can connect directly.

| Tool | Returns | Cite as |
|---|---|---|
| `get_machine_context` | Platform, site, software release and last update, available signals with nominal values and tolerances | — |
| `get_error_events` | Per-code summary and individual events in a look-back window (info events hidden by default) | `EV-…` |
| `get_telemetry_window` | Baseline vs recent mean, trend per day, first out-of-tolerance time, downsampled samples | `TS:<machine>:<signal>` |
| `lookup_error_code` | Description, severity, and every failure mode known to raise the code, with recommended checks | `EC-…` |
| `get_logbook` | Service logbook entries in a look-back window | `LB-…` |

"Now" is the dataset's fixed reference time, so the synthetic incidents always look current. Invalid calls return `{"error": "..."}` so the agent can correct itself.

## Layout

- `src/diagnostics_mcp/tools.py`: tool logic, independent of Functions (strictly typed, unit-tested)
- `function_app.py`: thin Functions layer; tool names, descriptions and schemas come from the signatures and docstrings
- `host.json`: MCP server name, version and client instructions

## Run locally

Requires [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local). No storage emulator is needed: the sample settings keep function keys on disk.

```bash
cd services/diagnostics-mcp
cp local.settings.sample.json local.settings.json
uv run func start            # MCP endpoint: http://localhost:7071/runtime/webhooks/mcp
```

Inspect it with any MCP client, for example:

```bash
npx @modelcontextprotocol/inspector   # transport "Streamable HTTP", URL as above
```

## Tests

```bash
uv run pytest services/diagnostics-mcp
```

`tests/test_function_app.py` indexes the real Function app and invokes the tools through the MCP argument wrapper. This catches schema regressions, such as optional parameters being advertised as required.

## Data-quality disclosure

Tool names and original scenario responses are unchanged. Capabilities come from each
machine's available telemetry; the independent pressure reference appears only on the new
sensor-fault machines. Legacy response serialization does not gain empty quality fields.

Irregular telemetry carries actual observation times. Summaries disclose missing and
duplicate observations, clock reversals and sensor disagreement when present. Statistics
use one observation per timestamp without filling gaps; sample timestamps retain elapsed
time. Empty or single-timestamp windows return a tool error instead of invented statistics.
Events expose receipt time when available, with duplicate, late-arrival and clock-skew
counts. Event time and receipt time are not interchangeable.
