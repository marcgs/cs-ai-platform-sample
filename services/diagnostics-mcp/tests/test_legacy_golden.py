"""Frozen on fae76ff before extending the generator; never regenerate to accept a change."""

import hashlib
import json
from pathlib import Path

from diagnostics_domain.catalog import ERROR_CODES, FAILURE_MODES, SIGNALS
from diagnostics_domain.dataset import load_seed
from diagnostics_mcp.tools import DiagnosticsTools

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_golden.json"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_original_seed_records_are_unchanged() -> None:
    frozen = json.loads(FIXTURE.read_text())
    assert frozen["revision"] == "fae76ff"
    original = load_seed().model_dump(mode="json")
    original["signals"] = original["signals"][: len(SIGNALS)]
    original["failure_modes"] = original["failure_modes"][: len(FAILURE_MODES)]
    original["error_codes"] = original["error_codes"][: len(ERROR_CODES)]
    original["machines"] = original["machines"][:20]
    original["telemetry"] = original["telemetry"][: 20 * len(SIGNALS)]
    original["error_events"] = [
        event for event in original["error_events"] if int(event["id"].removeprefix("EV-")) < 100000
    ]
    original["logbook"] = [
        entry for entry in original["logbook"] if int(entry["id"].removeprefix("LB-")) < 10000
    ]
    original_fields = (
        "id",
        "machine_id",
        "reported_at",
        "symptom",
        "onset",
        "expected_failure_mode",
    )
    original["scenarios"] = [
        {key: scenario[key] for key in original_fields} for scenario in original["scenarios"][:18]
    ]
    assert {key: _digest(value) for key, value in original.items()} == frozen["records"]


def test_original_tool_results_are_byte_identical() -> None:
    frozen = json.loads(FIXTURE.read_text())
    tools = DiagnosticsTools.from_seed()
    methods = {
        "machine_context": tools.machine_context,
        "logbook": tools.logbook,
        "error_events": tools.error_events,
        "telemetry_window": tools.telemetry_window,
        "error_code": tools.error_code,
    }
    for call in frozen["tools"]:
        actual = methods[call["name"]](*call["args"], **call["kwargs"])
        assert _digest(actual.model_dump(mode="json")) == call["sha256"], call
        assert (
            hashlib.sha256(actual.model_dump_json().encode()).hexdigest() == call["wire_sha256"]
        ), call
