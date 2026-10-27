"""Contract tests for the Functions layer: tool registration and MCP argument handling."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from diagnostics_mcp.tools import TOOL_NAMES

APP_PATH = Path(__file__).parents[1] / "function_app.py"
EXPECTED_TOOLS = set(TOOL_NAMES)

type Functions = dict[str, Any]


@pytest.fixture(scope="module")
def functions() -> Functions:
    """Index the app once: ``get_functions()`` registers bindings and can't run twice."""
    spec = importlib.util.spec_from_file_location("function_app", APP_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["function_app"] = module
    spec.loader.exec_module(module)
    return {f.get_function_name(): f for f in module.app.get_functions()}


async def _invoke(functions: Functions, name: str, arguments: dict[str, Any]) -> Any:
    handler = functions[name].get_user_function()
    return json.loads(await handler(json.dumps({"arguments": arguments})))


def test_registers_exactly_the_expected_tools(functions: Functions) -> None:
    assert set(functions) == EXPECTED_TOOLS


def test_tools_are_mcp_triggers_with_descriptions(functions: Functions) -> None:
    for name, function in functions.items():
        trigger = function.get_trigger()
        assert trigger.get_binding_name() == "mcpToolTrigger", name
        assert trigger.description, name
        for prop in json.loads(trigger.tool_properties):
            assert prop["description"], f"{name}.{prop['propertyName']}"


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("get_machine_context", {"machine_id": True}),
        ("get_error_events", {"machine_id": True, "hours": False, "include_info": False}),
        (
            "get_telemetry_window",
            {"machine_id": True, "signal": True, "hours": False, "sample_every_hours": False},
        ),
        ("lookup_error_code", {"code": True}),
        ("get_logbook", {"machine_id": True, "days": False}),
    ],
)
def test_only_parameters_without_defaults_are_required(
    functions: Functions, tool: str, expected: dict[str, bool]
) -> None:
    trigger = functions[tool].get_trigger()
    required = {p["propertyName"]: p["isRequired"] for p in json.loads(trigger.tool_properties)}
    assert required == expected


async def test_invocation_uses_defaults(functions: Functions) -> None:
    result = await _invoke(functions, "get_error_events", {"machine_id": "M-0001"})
    assert result["machine_id"] == "M-0001"
    assert "summary" in result


async def test_invocation_passes_arguments(functions: Functions) -> None:
    result = await _invoke(
        functions,
        "get_telemetry_window",
        {"machine_id": "M-0001", "signal": "stage_coolant_temp_c", "hours": 48},
    )
    assert result["ref"] == "TS:M-0001:stage_coolant_temp_c"


async def test_invalid_call_returns_error_payload(functions: Functions) -> None:
    result = await _invoke(functions, "get_machine_context", {"machine_id": "M-9999"})
    assert result == {"error": "Unknown machine: M-9999"}
