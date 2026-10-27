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
        dataset.failure_mode(scenario.expected_failure_mode)


def test_every_failure_mode_has_a_scenario(dataset: DiagnosticsDataset) -> None:
    covered = {s.expected_failure_mode for s in dataset.scenarios}
    assert covered == {m.id for m in dataset.failure_modes}


def test_shared_error_codes_require_discrimination(dataset: DiagnosticsDataset) -> None:
    modes_per_code: dict[str, set[str]] = {}
    for mode in dataset.failure_modes:
        for code in mode.error_codes:
            modes_per_code.setdefault(code, set()).add(mode.id)
    assert any(len(modes) > 1 for modes in modes_per_code.values())


def test_scenarios_emit_their_failure_mode_codes(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        mode = dataset.failure_mode(scenario.expected_failure_mode)
        codes = {e.code for e in dataset.events_for(scenario.machine_id, start=scenario.onset)}
        assert set(mode.error_codes) <= codes, scenario.id
        before = {e.code for e in dataset.events_for(scenario.machine_id, end=scenario.onset)}
        assert not set(mode.error_codes) & before, scenario.id


def test_scenario_telemetry_deviates_after_onset(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
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
        mode = dataset.failure_mode(scenario.expected_failure_mode)
        texts = {
            e.text for e in dataset.logbook_for(scenario.machine_id) if e.timestamp < scenario.onset
        }
        assert texts & set(mode.logbook_clues), scenario.id


def test_firmware_regression_machines_run_new_release(dataset: DiagnosticsDataset) -> None:
    for scenario in dataset.scenarios:
        if scenario.expected_failure_mode == "FM-06":
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
