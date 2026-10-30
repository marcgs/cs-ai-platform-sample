from datetime import timedelta
from itertools import pairwise

import pytest

from diagnostics_domain.dataset import load_seed
from diagnostics_domain.models import Scenario, Severity
from diagnostics_mcp.tools import DiagnosticsTools, ToolError, telemetry_ref


@pytest.fixture(scope="module")
def tools() -> DiagnosticsTools:
    return DiagnosticsTools.from_seed()


@pytest.fixture(scope="module")
def scenario() -> Scenario:
    return load_seed().scenario("SC-001")


def test_machine_context_lists_signals(tools: DiagnosticsTools) -> None:
    context = tools.machine_context("M-0001")
    assert context.machine_id == "M-0001"
    assert context.reference_time == tools.now
    assert len(context.signals) == 8


def test_error_events_summarize_fault_codes(tools: DiagnosticsTools, scenario: Scenario) -> None:
    mode = load_seed().failure_mode(scenario.expected_failure_mode)
    result = tools.error_events(scenario.machine_id, hours=72)
    codes = {s.ref for s in result.summary}
    assert set(mode.error_codes) <= codes
    assert all(e.ref.startswith("EV-") for e in result.events)
    for summary in result.summary:
        assert summary.count == sum(e.code == summary.ref for e in result.events)


def test_error_events_hide_info_by_default(tools: DiagnosticsTools) -> None:
    default = tools.error_events("M-0019", hours=168)
    with_info = tools.error_events("M-0019", hours=168, include_info=True)
    assert all(s.severity is not Severity.INFO for s in default.summary)
    assert any(s.severity is Severity.INFO for s in with_info.summary)


def test_error_events_respect_window(tools: DiagnosticsTools) -> None:
    result = tools.error_events("M-0001", hours=12, include_info=True)
    assert all(e.timestamp >= tools.now - timedelta(hours=12) for e in result.events)


def test_telemetry_window_detects_failure_signature(
    tools: DiagnosticsTools, scenario: Scenario
) -> None:
    mode = load_seed().failure_mode(scenario.expected_failure_mode)
    window = tools.telemetry_window(scenario.machine_id, mode.signature.signal, hours=168)
    assert window.ref == telemetry_ref(scenario.machine_id, mode.signature.signal)
    assert window.out_of_tolerance_count > 0
    assert window.first_out_of_tolerance is not None
    assert window.first_out_of_tolerance >= scenario.onset
    assert window.trend_per_day > 0
    assert abs(window.recent_mean - window.baseline_mean) > window.tolerance


def test_telemetry_window_is_quiet_for_healthy_signal(
    tools: DiagnosticsTools, scenario: Scenario
) -> None:
    window = tools.telemetry_window(scenario.machine_id, "chamber_pressure_pa", hours=168)
    assert window.out_of_tolerance_count == 0
    assert window.first_out_of_tolerance is None


def test_telemetry_samples_are_downsampled(tools: DiagnosticsTools) -> None:
    window = tools.telemetry_window("M-0001", "focus_offset_nm", hours=72, sample_every_hours=6)
    assert len(window.samples) == 12
    gaps = {b.timestamp - a.timestamp for a, b in pairwise(window.samples)}
    assert gaps == {timedelta(hours=6)}


def test_error_code_lists_all_failure_modes_sharing_it(tools: DiagnosticsTools) -> None:
    reference = tools.error_code("EC-2104")
    assert {c.failure_mode_id for c in reference.possible_causes} == {"FM-01", "FM-05", "FM-08"}


def test_logbook_contains_scenario_clue(tools: DiagnosticsTools, scenario: Scenario) -> None:
    mode = load_seed().failure_mode(scenario.expected_failure_mode)
    entries = tools.logbook(scenario.machine_id, days=30).entries
    assert all(e.ref.startswith("LB-") for e in entries)
    assert {e.text for e in entries} & set(mode.logbook_clues)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda t: t.machine_context("M-9999"), "Unknown machine"),
        (lambda t: t.error_events("M-0001", hours=0), "hours must be between"),
        (lambda t: t.telemetry_window("M-0001", "nope"), "Unknown signal"),
        (lambda t: t.telemetry_window("M-0001", "focus_offset_nm", hours=6), "hours"),
        (lambda t: t.error_code("EC-0000"), "Unknown error code"),
        (lambda t: t.logbook("M-0001", days=500), "days must be between"),
    ],
)
def test_invalid_calls_raise_tool_error(
    tools: DiagnosticsTools, call: object, message: str
) -> None:
    assert callable(call)
    with pytest.raises(ToolError, match=message):
        call(tools)


def test_new_signals_are_only_advertised_on_capable_machines(tools: DiagnosticsTools) -> None:
    data = load_seed()
    sensor = next(s for s in data.scenarios if s.category == "sensor_fault")
    assert len(tools.machine_context("M-0001").signals) == 8
    assert "chamber_pressure_reference_pa" in {
        signal.name for signal in tools.machine_context(sensor.machine_id).signals
    }
    with pytest.raises(ToolError, match="machine signal"):
        tools.telemetry_window("M-0001", "chamber_pressure_reference_pa")


def test_collection_anomalies_are_disclosed_without_compressing_time(
    tools: DiagnosticsTools,
) -> None:
    scenarios = [s for s in load_seed().scenarios if s.category == "data_gap"]
    gap = tools.telemetry_window(scenarios[0].machine_id, "chamber_pressure_pa")
    assert gap.data_quality is not None
    assert gap.data_quality.missing_count == 12
    assert gap.data_quality.longest_gap_minutes == 13 * 60
    assert gap.window_end == tools.now - timedelta(hours=1)
    edge_gap = tools.telemetry_window(scenarios[0].machine_id, "chamber_pressure_pa", hours=24)
    assert edge_gap.data_quality is not None
    assert edge_gap.data_quality.missing_count == 6
    duplicates = tools.telemetry_window(scenarios[1].machine_id, "chamber_pressure_pa")
    assert duplicates.data_quality is not None
    assert duplicates.data_quality.duplicate_count == 1
    events = tools.error_events(scenarios[1].machine_id)
    assert events.data_quality is not None
    assert events.data_quality.duplicate_count == 1
    late = tools.error_events(scenarios[2].machine_id)
    assert late.data_quality is not None
    assert late.data_quality.late_arrival_count == 4
    assert all(item.received_at > item.timestamp for item in late.events if item.received_at)
    skew = tools.telemetry_window(scenarios[3].machine_id, "chamber_pressure_pa")
    assert skew.data_quality is not None
    assert skew.data_quality.clock_reversal_count == 1
    skew_events = tools.error_events(scenarios[3].machine_id)
    assert skew_events.data_quality is not None
    assert skew_events.data_quality.clock_skew_count == 4


def test_bad_sensor_is_distinguished_from_physical_pressure(tools: DiagnosticsTools) -> None:
    scenarios = [s for s in load_seed().scenarios if s.category == "sensor_fault"]
    stuck = tools.telemetry_window(scenarios[0].machine_id, "chamber_pressure_pa")
    assert stuck.data_quality is not None
    assert stuck.data_quality.stuck_sensor
    assert stuck.data_quality.sensor_disagreement
    drift = tools.telemetry_window(scenarios[-1].machine_id, "chamber_pressure_pa")
    assert drift.data_quality is not None
    assert not drift.data_quality.stuck_sensor
    assert drift.data_quality.sensor_disagreement
    assert (
        tools.telemetry_window(
            scenarios[0].machine_id, "chamber_pressure_reference_pa"
        ).data_quality
        is None
    )


@pytest.mark.parametrize("count", [0, 1])
def test_insufficient_telemetry_returns_actionable_error(count: int) -> None:
    data = load_seed()
    original = data.telemetry[0]
    limited = original.model_copy(
        update={
            "start": data.reference_time - timedelta(hours=1),
            "values": original.values[:count],
        }
    )
    tools = DiagnosticsTools(data.model_copy(update={"telemetry": (limited, *data.telemetry[1:])}))
    with pytest.raises(ToolError, match=r"observations|distinct telemetry timestamps"):
        tools.telemetry_window(limited.machine_id, limited.signal)
