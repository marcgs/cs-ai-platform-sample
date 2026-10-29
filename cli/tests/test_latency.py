"""The latency probe validates payloads and never hides failed operations."""

import json
import subprocess
from unittest.mock import AsyncMock, Mock

import pytest
from agent_framework import MCPStreamableHTTPTool, tool
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from csai import latency
from csai.latency import Sample, digest, measure_transport, parse_context, summarize
from diagnostics_mcp.tools import DiagnosticsTools


@tool
def get_machine_context(machine_id: str) -> str:
    """Return a synthetic machine context."""
    return DiagnosticsTools.from_seed().machine_context(machine_id).model_dump_json()


def test_context_parser_matches_both_mcp_encodings():
    value = DiagnosticsTools.from_seed().machine_context("M-0007").model_dump_json()
    text = parse_context(CallToolResult(content=[TextContent(type="text", text=value)]))
    structured = parse_context(CallToolResult(content=[], structuredContent=json.loads(value)))
    assert digest(text) == digest(structured) == digest(value)
    assert digest('{"b":2,"a":1}') == digest('{ "a": 1, "b": 2 }')


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (CallToolResult(content=[], isError=True), ValueError),
        (CallToolResult(content=[]), ValueError),
        (
            CallToolResult(content=[TextContent(type="text", text='{"error":"missing"}')]),
            ValidationError,
        ),
    ],
)
def test_context_parser_rejects_protocol_and_domain_errors(result, error):
    with pytest.raises(error):
        parse_context(result)


async def test_probe_reuses_session_and_records_errors_without_retry(monkeypatch):
    value = DiagnosticsTools.from_seed().machine_context("M-0007").model_dump_json()
    client = MCPStreamableHTTPTool("diagnostics", "https://example.invalid")
    client.functions.append(get_machine_context)
    connect = AsyncMock()
    call = AsyncMock(side_effect=[value, TimeoutError("private endpoint"), '{"wrong":true}'])
    close = AsyncMock()
    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr(client, "call_tool", call)
    monkeypatch.setattr(client, "close", close)
    samples: list[Sample] = []
    await measure_transport(
        client,
        path="direct",
        machine_id="M-0007",
        expected=digest(value),
        warm_calls=2,
        session=0,
        record=samples.append,
    )
    connect.assert_awaited_once()
    close.assert_awaited_once()
    assert call.await_count == 3
    assert all(c.args == ("get_machine_context",) for c in call.await_args_list)
    assert all(c.kwargs == {"machine_id": "M-0007"} for c in call.await_args_list)
    assert [s.phase for s in samples] == ["initialize", "first", "warm", "warm", "close"]
    assert [s.error for s in samples] == [None, None, "TimeoutError", "PayloadMismatch", None]
    assert samples[1].matches_local is True
    assert samples[3].matches_local is False
    assert all(s.seconds >= 0 for s in samples)
    assert "private endpoint" not in samples[2].model_dump_json()


async def test_initialization_failure_still_closes_client(monkeypatch):
    client = MCPStreamableHTTPTool("diagnostics", "https://example.invalid")
    monkeypatch.setattr(client, "connect", AsyncMock(side_effect=TimeoutError()))
    close = AsyncMock()
    monkeypatch.setattr(client, "close", close)
    samples: list[Sample] = []
    await measure_transport(
        client,
        path="toolbox",
        machine_id="M-0007",
        expected="",
        warm_calls=1,
        session=0,
        record=samples.append,
    )
    assert [(s.phase, s.error) for s in samples] == [
        ("initialize", "TimeoutError"),
        ("close", None),
    ]
    close.assert_awaited_once()


@pytest.mark.parametrize("configured_output", ["table", "none"])
async def test_probe_reaches_both_paths_with_non_json_azure_cli_output(
    monkeypatch, tmp_path, configured_output
):
    monkeypatch.setenv("AZURE_CORE_OUTPUT", configured_output)

    def check_output(command, *, text):
        assert text
        if command[0] == "git":
            return "synthetic-revision\n"
        if "--output" in command and command[command.index("--output") + 1] == "json":
            return json.dumps({"systemKeys": {"mcp_extension": "NONSECRET_TEST_FIXTURE"}})
        return "Configured non-JSON output" if configured_output == "table" else ""

    monkeypatch.setattr(subprocess, "check_output", check_output)
    monkeypatch.setattr(latency, "AzureCliCredential", Mock(return_value=AsyncMock()))
    monkeypatch.setattr(latency, "FoundryToolbox", Mock())
    monkeypatch.setattr(latency, "MCPStreamableHTTPTool", Mock())
    measure = AsyncMock()
    monkeypatch.setattr(latency, "measure_transport", measure)

    assert await latency.run(
        environment={
            "AZURE_SUBSCRIPTION_ID": "synthetic-subscription",
            "AZURE_RESOURCE_GROUP": "synthetic-group",
            "DIAGNOSTICS_MCP_FUNCTION_NAME": "synthetic-mcp",
            "TOOLBOX_ENDPOINT": "https://example.invalid/toolbox",
            "DIAGNOSTICS_MCP_ENDPOINT": "https://example.invalid/mcp",
        },
        output=tmp_path / "latency.json",
        warm_calls=0,
        sessions=1,
        machine_id="M-0007",
        order=["toolbox", "direct"],
    )
    assert [call.kwargs["path"] for call in measure.await_args_list] == ["toolbox", "direct"]


def test_summary_separates_phases_and_excludes_failed_latencies():
    samples = [
        Sample(
            path="toolbox",
            phase=phase,
            session=0,
            started="synthetic",
            seconds=seconds,
            error=error,
            result_sha256=None,
            matches_local=None,
        )
        for phase, seconds, error in [
            ("first", 12, None),
            ("warm", 2, None),
            ("warm", 4, None),
            ("warm", 100, "TimeoutError"),
        ]
    ]
    rows = summarize(samples)
    assert rows[0]["median_s"] == 12
    assert rows[1] == {
        "path": "toolbox",
        "phase": "warm",
        "attempts": 3,
        "errors": 1,
        "min_s": 2,
        "median_s": 3,
        "p95_s": 4,
        "max_s": 4,
    }
