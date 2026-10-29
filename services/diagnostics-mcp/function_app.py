"""Azure Functions entry point: exposes the diagnostic tools as an MCP server.

The host serves the tools at ``/runtime/webhooks/mcp``. Tool names, descriptions and
parameter schemas are derived from the function signatures and docstrings below.
"""

import json
from typing import TYPE_CHECKING

import azure.functions as func

from diagnostics_mcp.tools import DiagnosticsTools, ToolError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
tools = DiagnosticsTools.from_seed()

MACHINE_ID = "Machine identifier, for example M-0001."


def _respond(call: Callable[[], BaseModel]) -> str:
    """Serialize a tool result; invalid calls become an error the agent can act on."""
    try:
        return call().model_dump_json()
    except ToolError as error:
        return json.dumps({"error": str(error)})


@app.mcp_tool()
@app.mcp_tool_property(arg_name="machine_id", description=MACHINE_ID)
def get_machine_context(machine_id: str) -> str:
    """Get a machine's configuration (platform, site, software release and date of the last
    software update), the current reference time, and the telemetry signals available for it
    with their nominal values and tolerances."""
    return _respond(lambda: tools.machine_context(machine_id))


@app.mcp_tool()
@app.mcp_tool_property(arg_name="machine_id", description=MACHINE_ID)
@app.mcp_tool_property(
    arg_name="hours",
    description="Look-back window in hours (1-168). Default 48.",
    is_required=False,
)
@app.mcp_tool_property(
    arg_name="include_info",
    description="Include informational events such as lot start/complete. Default false.",
    is_required=False,
)
def get_error_events(machine_id: str, hours: int = 48, include_info: bool = False) -> str:
    """List a machine's error events in a look-back window: a per-code summary (count, first
    and last seen) plus the individual events. Each event has a ref (EV-...) to cite."""
    return _respond(lambda: tools.error_events(machine_id, hours, include_info))


@app.mcp_tool()
@app.mcp_tool_property(arg_name="machine_id", description=MACHINE_ID)
@app.mcp_tool_property(
    arg_name="signal", description="Signal name as listed by get_machine_context."
)
@app.mcp_tool_property(
    arg_name="hours",
    description="Look-back window in hours (24-168). Default 72.",
    is_required=False,
)
@app.mcp_tool_property(
    arg_name="sample_every_hours",
    description="Spacing of the returned samples in hours (1-24). Default 6.",
    is_required=False,
)
def get_telemetry_window(
    machine_id: str, signal: str, hours: int = 72, sample_every_hours: int = 6
) -> str:
    """Summarize one telemetry signal over a look-back window: baseline vs recent mean, recent
    standard deviation, min/max, linear trend per day, count and first time of readings outside
    tolerance, and downsampled samples. Cite it by its ref (TS:<machine>:<signal>)."""
    return _respond(lambda: tools.telemetry_window(machine_id, signal, hours, sample_every_hours))


@app.mcp_tool()
@app.mcp_tool_property(arg_name="code", description="Error code, for example EC-2101.")
def lookup_error_code(code: str) -> str:
    """Look up an error code in the diagnostic reference: description, severity, subsystem and
    the failure modes known to raise it, with recommended checks. Several failure modes can
    share a code, so use telemetry and logbook evidence to discriminate between them."""
    return _respond(lambda: tools.error_code(code))


@app.mcp_tool()
@app.mcp_tool_property(arg_name="machine_id", description=MACHINE_ID)
@app.mcp_tool_property(
    arg_name="days",
    description="Look-back window in days (1-120). Default 30.",
    is_required=False,
)
def get_logbook(machine_id: str, days: int = 30) -> str:
    """List a machine's service logbook entries (maintenance, interventions, observations) in a
    look-back window. Each entry has a ref (LB-...) to cite."""
    return _respond(lambda: tools.logbook(machine_id, days))
