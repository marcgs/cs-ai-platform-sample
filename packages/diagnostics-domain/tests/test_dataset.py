from collections import Counter
from datetime import timedelta

import pytest

from diagnostics_domain.dataset import DiagnosticsDataset, UnknownRecordError, load_seed
from diagnostics_domain.generator import RAMP_HOURS, generate
from diagnostics_domain.models import SignatureKind


@pytest.fixture(scope="module")
def dataset() -> DiagnosticsDataset:
    return load_seed()


def test_generator_is_deterministic() -> None:
    assert generate() == generate()


def test_committed_seed_matches_generator(dataset: DiagnosticsDataset) -> None:
    assert dataset == generate(), "Seed is stale: run `uv run generate-seed-data`."


def test_identifiers_are_unique(dataset: DiagnosticsDataset) -> None:
    for ids in (
        [m.id for m in dataset.machines],
        [e.id for e in dataset.error_events],
        [e.id for e in dataset.logbook],
        [c.id for c in dataset.historical_cases],
        [s.id for s in dataset.scenarios],
    ):
        assert len(ids) == len(set(ids))


def test_references_resolve(dataset: DiagnosticsDataset) -> None:
    for event in dataset.error_events:
        dataset.machine(event.machine_id)
        dataset.error_code(event.code)
    for mode in dataset.failure_modes:
        for code in mode.error_codes:
            dataset.error_code(code)
        dataset.signal(mode.signature.signal)
    for case in dataset.historical_cases:
        dataset.machine(case.machine_id)
        dataset.failure_mode(case.confirmed_failure_mode)
    for scenario in dataset.scenarios:
        dataset.machine(scenario.machine_id)
        if scenario.expected_failure_mode != "unknown":
            dataset.failure_mode(scenario.expected_failure_mode)


def test_every_failure_mode_has_a_scenario(dataset: DiagnosticsDataset) -> None:
    covered = {s.expected_failure_mode for s in dataset.scenarios} - {"unknown"}
    assert covered == {m.id for m in dataset.failure_modes}


def test_shared_error_codes_require_discrimination(dataset: DiagnosticsDataset) -> None:
    modes_per_code: dict[str, set[str]] = {}
    for mode in dataset.failure_modes:
        for code in mode.error_codes:
            modes_per_code.setdefault(code, set()).add(mode.id)
    assert any(len(modes) > 1 for modes in modes_per_code.values())


def test_scenarios_emit_their_failure_mode_codes(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        if scenario.category != "clean":
            continue
        mode = dataset.failure_mode(scenario.expected_failure_mode)
        codes = {e.code for e in dataset.events_for(scenario.machine_id, start=scenario.onset)}
        assert set(mode.error_codes) <= codes, scenario.id
        before = {e.code for e in dataset.events_for(scenario.machine_id, end=scenario.onset)}
        assert not set(mode.error_codes) & before, scenario.id


def test_scenario_telemetry_deviates_after_onset(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        if scenario.category != "clean":
            continue
        mode = dataset.failure_mode(scenario.expected_failure_mode)
        signal = dataset.signal(mode.signature.signal)
        before = dataset.telemetry_for(
            scenario.machine_id, signal.name, end=scenario.onset - timedelta(hours=1)
        ).values
        settled = dataset.telemetry_for(
            scenario.machine_id, signal.name, start=scenario.onset + timedelta(hours=RAMP_HOURS / 2)
        ).values
        assert all(abs(v - signal.nominal) < signal.tolerance for v in before), scenario.id
        if mode.signature.kind is SignatureKind.NOISE_UP:
            assert max(abs(v - signal.nominal) for v in settled) > signal.tolerance, scenario.id
        else:
            assert abs(settled[-1] - signal.nominal) > signal.tolerance, scenario.id


def test_scenario_machines_have_a_logbook_clue(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        if scenario.category != "clean":
            continue
        mode = dataset.failure_mode(scenario.expected_failure_mode)
        texts = {
            e.text for e in dataset.logbook_for(scenario.machine_id) if e.timestamp < scenario.onset
        }
        assert texts & set(mode.logbook_clues), scenario.id


def test_firmware_regression_machines_run_new_release(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        if scenario.category == "clean" and scenario.expected_failure_mode == "FM-06":
            machine = dataset.machine(scenario.machine_id)
            assert machine.software_release == "R7.4"
            assert machine.last_software_update <= scenario.onset.date()


def test_telemetry_slice_respects_bounds(dataset: DiagnosticsDataset) -> None:
    full = dataset.telemetry_for("M-0001", "chamber_pressure_pa")
    start = full.start + timedelta(hours=10)
    end = full.start + timedelta(hours=19)
    sliced = dataset.telemetry_for("M-0001", "chamber_pressure_pa", start=start, end=end)
    assert sliced.start == start
    assert sliced.values == full.values[10:20]


def test_unknown_lookups_raise(dataset: DiagnosticsDataset) -> None:
    with pytest.raises(UnknownRecordError, match="machine"):
        dataset.machine("M-9999")
    with pytest.raises(UnknownRecordError, match="signal"):
        dataset.telemetry_for("M-0001", "no_such_signal")


def test_challenge_counts_and_hidden_identity(dataset: DiagnosticsDataset) -> None:
    counts = Counter(scenario.category for scenario in dataset.scenarios)
    assert counts.pop("clean") == 18
    assert len(counts) == 8
    assert set(counts.values()) == {4}
    for scenario in dataset.scenarios:
        rendered = scenario.incident_input()
        if scenario.category == "missing_machine":
            assert "M-" not in rendered
            assert scenario.expected_failure_mode == "unknown"
        else:
            assert rendered.startswith(f"{scenario.machine_id}:")


def test_decisive_refs_belong_to_machine(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        assert scenario.confirming_checks
        if scenario.category != "missing_machine":
            assert scenario.decisive_refs
        for ref in scenario.decisive_refs:
            if ref.startswith("TS:"):
                _, machine, signal = ref.split(":")
                assert machine == scenario.machine_id
                assert dataset.telemetry_for(machine, signal).values
            elif ref.startswith("EV-"):
                assert any(
                    event.id == ref and event.machine_id == scenario.machine_id
                    for event in dataset.error_events
                )
            elif ref.startswith("LB-"):
                assert any(
                    entry.id == ref and entry.machine_id == scenario.machine_id
                    for entry in dataset.logbook
                )
            else:
                pytest.fail(f"Unresolved decisive ref {ref}")
        for mode in (*scenario.acceptable_failure_modes, *scenario.ruled_out_failure_modes):
            dataset.failure_mode(mode)


def test_collection_gaps_preserve_actual_observation_times(dataset: DiagnosticsDataset) -> None:
    scenario = next(s for s in dataset.scenarios if s.category == "data_gap")
    series = dataset.telemetry_for(scenario.machine_id, "chamber_pressure_pa")
    assert len(series.values) == len(series.timestamps) == 156
    assert series.timestamps[138] - series.timestamps[137] == timedelta(hours=13)
    assert series.timestamps[-1] == dataset.reference_time - timedelta(hours=1)
    sliced = dataset.telemetry_for(
        scenario.machine_id,
        "chamber_pressure_pa",
        start=series.timestamps[137],
        end=series.timestamps[139],
    )
    assert sliced.timestamps == series.timestamps[137:140]
    assert sliced.values == series.values[137:140]


def test_sensor_fault_has_healthy_independent_reference(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        if scenario.category != "sensor_fault":
            continue
        assert scenario.expected_failure_mode == "FM-09"
        reference = dataset.telemetry_for(scenario.machine_id, "chamber_pressure_reference_pa")
        assert all(abs(value - 0.5) < 0.1 for value in reference.values)
        primary = dataset.telemetry_for(scenario.machine_id, "chamber_pressure_pa")
        assert primary.values[-1] > 0.8


def test_challenge_events_support_compact_feedback_code_matching(
    dataset: DiagnosticsDataset,
) -> None:
    for scenario in dataset.scenarios:
        if scenario.category == "clean" or scenario.expected_failure_mode == "unknown":
            continue
        mode = dataset.failure_mode(scenario.expected_failure_mode)
        compact_events = dataset.events_for(scenario.machine_id, scenario.onset)[-4:]
        assert mode.error_codes[-1] in {event.code for event in compact_events}, scenario.id


def test_overlapping_update_context_agrees_with_causal_failure_mode(
    dataset: DiagnosticsDataset,
) -> None:
    for scenario in dataset.scenarios:
        if scenario.category != "overlapping":
            continue
        entry = next(
            entry
            for entry in dataset.logbook_for(scenario.machine_id)
            if entry.id in scenario.decisive_refs
        )
        if scenario.expected_failure_mode == "FM-06":
            assert "temporal distraction" not in entry.text
            assert "watchdog resets began after the recent software update" in entry.text
            machine = dataset.machine(scenario.machine_id)
            assert machine.last_software_update <= scenario.onset.date()
        else:
            assert "temporal distraction" in entry.text
