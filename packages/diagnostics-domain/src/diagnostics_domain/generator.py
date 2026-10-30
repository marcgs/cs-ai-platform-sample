"""Deterministic generator for the synthetic seed dataset.

Run ``uv run generate-seed-data`` after changing the catalog or this module. A test fails if
the committed seed no longer matches the generator output.
"""

import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from diagnostics_domain.catalog import BACKGROUND_CODES, ERROR_CODES, FAILURE_MODES, SIGNALS
from diagnostics_domain.dataset import SEED_RESOURCE, DiagnosticsDataset
from diagnostics_domain.harder import extend_dataset
from diagnostics_domain.models import (
    ErrorEvent,
    FailureMode,
    HistoricalCase,
    LogbookEntry,
    Machine,
    Scenario,
    Signal,
    SignatureKind,
    TelemetrySeries,
    TelemetrySignature,
)

DEFAULT_SEED = 20261020
REFERENCE_TIME = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
WINDOW = timedelta(days=7)
INTERVAL_MINUTES = 60
MACHINE_COUNT = 20
SCENARIO_COUNT = 18
HISTORICAL_CASE_COUNT = 40
RAMP_HOURS = 48

PLATFORMS = ("Aurora X1", "Aurora X2", "Borealis S3")
SITES = ("Fab North", "Fab South", "Fab East")
BASE_RELEASES = ("R7.2", "R7.3")
FIRMWARE_REGRESSION_RELEASE = "R7.4"
FIRMWARE_REGRESSION_ID = "FM-06"
ROUTINE_LOGBOOK_TEXTS = (
    "Routine inspection completed, no findings.",
    "Lot recipe changed per fab request.",
    "Wafer handler calibration completed.",
    "Shift handover: no open issues reported.",
    "Log collection performed for remote support.",
    "Exposure dose calibration verified within specification.",
)
ENGINEER_ROLES = ("field service engineer", "shift engineer", "remote support specialist")


def generate(seed: int = DEFAULT_SEED) -> DiagnosticsDataset:
    rng = random.Random(seed)
    window_start = REFERENCE_TIME - WINDOW

    scenario_plan = _plan_scenarios(rng)
    machines = _machines(rng, scenario_plan)
    scenarios = _scenarios(rng, scenario_plan)
    by_machine = {scenario.machine_id: scenario for scenario in scenarios}
    modes = {mode.id: mode for mode in FAILURE_MODES}

    telemetry = tuple(
        _series(rng, machine.id, signal, window_start, by_machine.get(machine.id), modes)
        for machine in machines
        for signal in SIGNALS
    )

    legacy = DiagnosticsDataset(
        reference_time=REFERENCE_TIME,
        signals=SIGNALS,
        error_codes=ERROR_CODES,
        failure_modes=FAILURE_MODES,
        machines=machines,
        error_events=_error_events(rng, machines, by_machine, modes, window_start),
        telemetry=telemetry,
        logbook=_logbook(rng, machines, by_machine, modes, window_start),
        historical_cases=_historical_cases(rng, machines),
        scenarios=scenarios,
    )
    return extend_dataset(legacy, seed)


def _plan_scenarios(rng: random.Random) -> list[tuple[str, str, datetime]]:
    """(machine id, failure mode id, onset) for each active incident."""
    plan: list[tuple[str, str, datetime]] = []
    for index in range(SCENARIO_COUNT):
        mode = FAILURE_MODES[index % len(FAILURE_MODES)]
        onset = REFERENCE_TIME - timedelta(hours=rng.randint(24, 60))
        plan.append((_machine_id(index + 1), mode.id, onset))
    return plan


def _machine_id(number: int) -> str:
    return f"M-{number:04d}"


def _machines(
    rng: random.Random, scenario_plan: list[tuple[str, str, datetime]]
) -> tuple[Machine, ...]:
    regressions = {
        machine_id: onset
        for machine_id, mode_id, onset in scenario_plan
        if mode_id == FIRMWARE_REGRESSION_ID
    }
    machines: list[Machine] = []
    for number in range(1, MACHINE_COUNT + 1):
        machine_id = _machine_id(number)
        install = date(2019, 1, 1) + timedelta(days=rng.randint(0, 5 * 365))
        if machine_id in regressions:
            release = FIRMWARE_REGRESSION_RELEASE
            updated = (regressions[machine_id] - timedelta(hours=6)).date()
        else:
            release = rng.choice(BASE_RELEASES)
            updated = REFERENCE_TIME.date() - timedelta(days=rng.randint(30, 200))
        machines.append(
            Machine(
                id=machine_id,
                platform=rng.choice(PLATFORMS),
                site=rng.choice(SITES),
                install_date=install,
                software_release=release,
                last_software_update=updated,
            )
        )
    return tuple(machines)


def _scenarios(
    rng: random.Random, scenario_plan: list[tuple[str, str, datetime]]
) -> tuple[Scenario, ...]:
    modes = {mode.id: mode for mode in FAILURE_MODES}
    return tuple(
        Scenario(
            id=f"SC-{index:03d}",
            machine_id=machine_id,
            reported_at=REFERENCE_TIME,
            symptom=rng.choice(modes[mode_id].symptoms),
            onset=onset,
            expected_failure_mode=mode_id,
        )
        for index, (machine_id, mode_id, onset) in enumerate(scenario_plan, start=1)
    )


def _series(
    rng: random.Random,
    machine_id: str,
    signal: Signal,
    window_start: datetime,
    scenario: Scenario | None,
    modes: dict[str, FailureMode],
) -> TelemetrySeries:
    step = timedelta(minutes=INTERVAL_MINUTES)
    points = WINDOW // step
    signature = modes[scenario.expected_failure_mode].signature if scenario else None
    if signature is not None and signature.signal != signal.name:
        signature = None

    values: list[float] = []
    for index in range(points):
        value = signal.nominal + rng.gauss(0, signal.noise)
        timestamp = window_start + index * step
        if signature is not None and scenario is not None and timestamp >= scenario.onset:
            value += _deviation(rng, signal, signature, timestamp - scenario.onset)
        values.append(round(value, 4))

    return TelemetrySeries(
        machine_id=machine_id,
        signal=signal.name,
        unit=signal.unit,
        start=window_start,
        interval_minutes=INTERVAL_MINUTES,
        values=tuple(values),
    )


def _deviation(
    rng: random.Random, signal: Signal, signature: TelemetrySignature, since_onset: timedelta
) -> float:
    """Offset a failure signature adds to a healthy reading, ramping in over RAMP_HOURS."""
    progress = min(since_onset / timedelta(hours=RAMP_HOURS), 1.0)
    match signature.kind:
        case SignatureKind.RAMP_UP:
            return signature.magnitude * progress
        case SignatureKind.RAMP_DOWN:
            return -signature.magnitude * progress
        case SignatureKind.NOISE_UP:
            return rng.gauss(0, signal.noise * signature.magnitude * progress)
        case SignatureKind.LEVEL_UP:
            return signature.magnitude


def _error_events(
    rng: random.Random,
    machines: tuple[Machine, ...],
    by_machine: dict[str, Scenario],
    modes: dict[str, FailureMode],
    window_start: datetime,
) -> tuple[ErrorEvent, ...]:
    descriptions = {code.code: code.description for code in ERROR_CODES}
    raw: list[tuple[datetime, str, str]] = []

    for machine in machines:
        timestamp = window_start + timedelta(minutes=rng.randint(0, 120))
        while timestamp < REFERENCE_TIME:
            raw.append((timestamp, machine.id, rng.choice(BACKGROUND_CODES)))
            timestamp += timedelta(minutes=rng.randint(90, 300))

        scenario = by_machine.get(machine.id)
        if scenario is None:
            continue
        for code in modes[scenario.expected_failure_mode].error_codes:
            timestamp = scenario.onset + timedelta(hours=rng.randint(4, 10))
            while timestamp < REFERENCE_TIME:
                raw.append((timestamp, machine.id, code))
                timestamp += timedelta(hours=rng.randint(4, 9))

    raw.sort()
    return tuple(
        ErrorEvent(
            id=f"EV-{index:06d}",
            machine_id=machine_id,
            timestamp=timestamp,
            code=code,
            message=descriptions[code],
        )
        for index, (timestamp, machine_id, code) in enumerate(raw, start=1)
    )


def _logbook(
    rng: random.Random,
    machines: tuple[Machine, ...],
    by_machine: dict[str, Scenario],
    modes: dict[str, FailureMode],
    window_start: datetime,
) -> tuple[LogbookEntry, ...]:
    raw: list[tuple[datetime, str, str, str]] = []

    for machine in machines:
        for _ in range(rng.randint(3, 5)):
            timestamp = window_start - timedelta(days=14) + timedelta(hours=rng.randint(0, 20 * 24))
            raw.append(
                (
                    timestamp,
                    machine.id,
                    rng.choice(ENGINEER_ROLES),
                    rng.choice(ROUTINE_LOGBOOK_TEXTS),
                )
            )

        scenario = by_machine.get(machine.id)
        if scenario is not None:
            clue = rng.choice(modes[scenario.expected_failure_mode].logbook_clues)
            timestamp = scenario.onset - timedelta(hours=rng.randint(6, 30))
            raw.append((timestamp, machine.id, "field service engineer", clue))

        # Red herring: an old clue for a different failure mode, well before the window.
        if rng.random() < 0.3:
            other = rng.choice(
                [m for m in FAILURE_MODES if not scenario or m.id != scenario.expected_failure_mode]
            )
            timestamp = window_start - timedelta(days=rng.randint(30, 90))
            raw.append((timestamp, machine.id, "field service engineer", other.logbook_clues[0]))

    raw.sort()
    return tuple(
        LogbookEntry(id=f"LB-{index:05d}", machine_id=m, timestamp=t, author_role=role, text=text)
        for index, (t, m, role, text) in enumerate(raw, start=1)
    )


def _historical_cases(
    rng: random.Random, machines: tuple[Machine, ...]
) -> tuple[HistoricalCase, ...]:
    raw: list[tuple[datetime, str, FailureMode]] = []
    first = datetime(2025, 1, 1, tzinfo=UTC)
    span_hours = int((datetime(2026, 9, 30, tzinfo=UTC) - first) / timedelta(hours=1))
    for _ in range(HISTORICAL_CASE_COUNT):
        opened = first + timedelta(hours=rng.randint(0, span_hours))
        raw.append((opened, rng.choice(machines).id, rng.choice(FAILURE_MODES)))

    raw.sort(key=lambda item: item[0])
    return tuple(
        HistoricalCase(
            id=f"HC-{index:04d}",
            machine_id=machine_id,
            opened=opened,
            symptom=rng.choice(mode.symptoms),
            confirmed_failure_mode=mode.id,
            resolution=f"Root cause confirmed: {mode.root_cause} "
            f"Resolved by: {mode.recommended_checks[-1]}",
            downtime_hours=round(rng.uniform(2, 24), 1),
        )
        for index, (opened, machine_id, mode) in enumerate(raw, start=1)
    )


def seed_path() -> Path:
    return Path(__file__).parent / SEED_RESOURCE


def main() -> None:
    path = seed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate().model_dump_json() + "\n", encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
