"""Offline replay of captured calls through the same implementation as MCP."""

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from diagnostics_domain.tools import DiagnosticsTools, ToolError

if TYPE_CHECKING:
    from collections.abc import Callable

    from cs_platform.episodes import Episode, ToolCall


class ReplayIssue(BaseModel):
    """A deterministic rejection, indexed by the call's position in the transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_index: int
    tool_name: str
    reason: str


class ReplayResult(BaseModel):
    """Replay admission and ordered fingerprints; no reviewer truth is consulted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replayable: bool
    fingerprints: list[str]
    issues: list[ReplayIssue]


def tool_fingerprint(call: ToolCall) -> str:
    """Hash the normalized tool name, arguments and canonical JSON result (not timings)."""
    payload = {
        "name": call.name.rsplit("___", 1)[-1],
        "arguments": call.arguments,
        "result": json.loads(call.result) if call.result is not None else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def execute_tool_call(call: ToolCall, tools: DiagnosticsTools) -> str:
    """Dispatch only today's five diagnostic tools; return the MCP wire JSON."""
    methods: dict[str, Callable[..., BaseModel]] = {
        "get_machine_context": tools.machine_context,
        "get_error_events": tools.error_events,
        "get_telemetry_window": tools.telemetry_window,
        "lookup_error_code": tools.error_code,
        "get_logbook": tools.logbook,
    }
    name = call.name.rsplit("___", 1)[-1]
    if name not in methods:
        raise ValueError(f"Unsupported offline tool: {name}")
    try:
        return methods[name](**call.arguments).model_dump_json()
    except ToolError as exc:
        return json.dumps({"error": str(exc)})


def replay_episode(episode: Episode, *, tools: DiagnosticsTools | None = None) -> ReplayResult:
    """Fail closed on incomplete captures, unsupported calls and fingerprint mismatches."""
    tools = tools if tools is not None else DiagnosticsTools.from_seed()
    fingerprints: list[str] = []
    issues: list[ReplayIssue] = []
    if (
        episode.status == "running"
        or episode.completed_at is None
        or episode.truncated
        or not episode.tool_calls
    ):
        issues.append(ReplayIssue(call_index=-1, tool_name="", reason="Incomplete episode capture"))
    for index, call in enumerate(episode.tool_calls):
        reason: str | None = None
        if call.result_truncated or call.error or call.result is None:
            reason = "Incomplete tool capture"
        else:
            try:
                captured = tool_fingerprint(call)
                fingerprints.append(captured)
                replayed = call.model_copy(update={"result": execute_tool_call(call, tools)})
                if captured != tool_fingerprint(replayed):
                    reason = "Tool fingerprint mismatch"
            except (TypeError, ValueError) as exc:
                reason = str(exc)
        if reason is not None:
            issues.append(ReplayIssue(call_index=index, tool_name=call.name, reason=reason))
    return ReplayResult(replayable=not issues, fingerprints=fingerprints, issues=issues)
