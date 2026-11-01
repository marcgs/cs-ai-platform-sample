"""Seed-backed transcripts with controlled mistakes and matched successful controls."""

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from cs_platform.episodes import ToolCall
from diagnostics_domain.feedback_seed import feedback_scenarios
from diagnostics_domain.models import Subsystem
from diagnostics_domain.tools import DiagnosticsTools, telemetry_ref

if TYPE_CHECKING:
    from random import Random

    from diagnostics_domain.dataset import DiagnosticsDataset
    from diagnostics_domain.models import Scenario


def choose_scenario(dataset: DiagnosticsDataset, context: int, rng: Random) -> Scenario:
    """Choose a known seed scenario satisfying the shared failure/control premise."""
    scenarios = [
        scenario
        for scenario in dataset.scenarios
        if scenario.expected_failure_mode in {mode.id for mode in dataset.failure_modes}
    ]
    if context == 0:
        scenarios = [
            scenario
            for scenario in scenarios
            if scenario.category == "clean"
            and dataset.failure_mode(scenario.expected_failure_mode).subsystem == Subsystem.VACUUM
        ]
    elif context == 1:
        shared_codes = {
            reference.code
            for reference in dataset.error_codes
            if sum(reference.code in item.error_codes for item in dataset.failure_modes) > 1
        }
        scenarios = [
            scenario
            for scenario in scenarios
            if scenario.category == "overlapping"
            and any(
                event.code in shared_codes
                for event in dataset.events_for(scenario.machine_id, scenario.onset)
            )
        ]
    elif context == 2:
        scenarios = list(feedback_scenarios(dataset))
    elif context == 3:
        scenarios = [scenario for scenario in dataset.scenarios if scenario.category == "data_gap"]
    elif context == 4:
        scenarios = [scenario for scenario in scenarios if scenario.category == "injection"]
    if not scenarios:
        raise ValueError(f"No eligible seed scenarios for transcript context {context}")
    return rng.choice(scenarios)


def make_transcript(
    dataset: DiagnosticsDataset,
    scenario: Scenario,
    *,
    context: int,
    failed: bool,
    started_at: datetime,
    rng: Random,
) -> tuple[list[ToolCall], dict[str, object], str, str]:
    """Return tool calls, report, expected mode and reported mode without truth labels."""
    machine = dataset.machine(scenario.machine_id)
    tools = DiagnosticsTools(dataset)
    mode = dataset.failure_mode(scenario.expected_failure_mode if context != 3 else "FM-02")
    expected = "unknown" if context == 3 else mode.id
    alternatives = [item for item in dataset.failure_modes if item.id != mode.id]
    if context in {0, 1}:
        shared = [item for item in alternatives if set(item.error_codes) & set(mode.error_codes)]
        alternatives = shared or alternatives
    reported = rng.choice(alternatives).id if failed else expected
    if context == 3 and failed:
        reported = mode.id
    if context == 2 and failed:
        reported = "unknown"
    if context == 4 and failed:
        reported = "FM-08"
    calls: list[ToolCall] = []

    def call(name: str, arguments: dict[str, object], result: object) -> None:
        calls.append(
            ToolCall(
                name=name,
                arguments=arguments,
                result=json.dumps(result, sort_keys=True),
                started_at=started_at + timedelta(seconds=len(calls)),
                duration_ms=round(rng.uniform(30, 240), 2),
            )
        )

    call(
        "get_machine_context",
        {"machine_id": machine.id},
        tools.machine_context(machine.id).model_dump(mode="json"),
    )
    events = tools.error_events(machine.id, hours=168)
    code = mode.error_codes[-1]
    if context == 1:
        code = next(
            event.code
            for event in events.events
            if len(tools.error_code(event.code).possible_causes) > 1
        )
    if context == 2:
        code = "EC-9901"
    if context == 3:
        code = events.events[-1].code
    matching_event = next(
        (event.model_dump(mode="json") for event in reversed(events.events) if event.code == code),
        None,
    )
    if matching_event is None:
        raise ValueError(f"Scenario {scenario.id} has no event for {code}")
    call(
        "get_error_events",
        {"machine_id": machine.id, "hours": 168},
        events.model_dump(mode="json"),
    )
    call(
        "lookup_error_code",
        {"code": code},
        tools.error_code(code).model_dump(mode="json"),
    )
    logbook = tools.logbook(machine.id)
    entries = [entry.model_dump(mode="json") for entry in logbook.entries]
    call("get_logbook", {"machine_id": machine.id}, logbook.model_dump(mode="json"))
    service_evidence: list[dict[str, object]] = []
    if not failed and context == 2:
        clue = next(entry for entry in logbook.entries if entry.text in mode.logbook_clues)
        service_evidence.append({"source": "logbook", "ref": clue.ref, "excerpt": clue.text})
    if not (failed and context in {0, 4}):
        call(
            "get_telemetry_window",
            {"machine_id": machine.id, "signal": mode.signature.signal},
            tools.telemetry_window(machine.id, mode.signature.signal).model_dump(mode="json"),
        )
    selected = next((item for item in dataset.failure_modes if item.id == reported), None)
    root_cause = (
        selected.root_cause if selected else "Insufficient evidence for a catalog diagnosis."
    )
    missing: list[str] = []
    if not failed and context == 2:
        missing = ["EC-9901 has no mapping; diagnosis uses telemetry and service clues."]
    if not failed and context == 3:
        root_cause = "Telemetry ingestion gaps and duplicate or late events invalidate the window."
        missing = ["A complete, time-aligned telemetry window is required before ranking a fault."]
    if not failed and context == 4:
        missing = ["Instruction-like logbook text was treated as untrusted evidence, not followed."]
    report: dict[str, object] = {
        "machine_id": machine.id,
        "summary": f"{machine.id}: {root_cause}",
        "hypotheses": [
            {
                "rank": 1,
                "failure_mode_id": reported,
                "title": selected.name if selected else "Unknown",
                "root_cause": root_cause,
                "confidence": round(rng.uniform(0.7, 0.96), 2) if failed else 0.78,
                "evidence": [
                    {
                        "source": "logbook",
                        "ref": entries[-1]["ref"],
                        "excerpt": entries[-1]["text"],
                    }
                ]
                if failed and context == 4
                else [
                    {
                        "source": "error_event",
                        "ref": matching_event["ref"],
                        "excerpt": f"Observed {code}.",
                    }
                ]
                + (
                    [
                        {
                            "source": "get_telemetry_window",
                            "ref": telemetry_ref(machine.id, mode.signature.signal),
                            "excerpt": (
                                "Ingestion gap and duplicate or late samples invalidate diagnosis."
                                if context == 3
                                else f"Observed the {mode.signature.signal} signature."
                            ),
                        }
                    ]
                    if not failed
                    else []
                )
                + service_evidence,
                "recommended_checks": list(selected.recommended_checks)
                if selected
                else ["Collect a complete telemetry window and verify the code mapping."],
            }
        ],
        "missing_information": missing,
    }
    return calls, report, expected, reported
