"""Additive seed records for feedback's unmapped-code, known-signature incidents."""

from typing import TYPE_CHECKING

from diagnostics_domain.models import ErrorCode, Severity, Subsystem

if TYPE_CHECKING:
    from diagnostics_domain.dataset import DiagnosticsDataset
    from diagnostics_domain.models import Scenario


def feedback_scenarios(dataset: DiagnosticsDataset) -> tuple[Scenario, ...]:
    """Expose copied incident metadata with the same IDs allocated by seed extension."""
    copied: list[Scenario] = []
    for index, scenario in enumerate(dataset.scenarios[:4]):
        machine_id = f"M-{53 + index:04d}"
        refs = {
            f"TS:{scenario.machine_id}:{series.signal}": f"TS:{machine_id}:{series.signal}"
            for series in dataset.telemetry
            if series.machine_id == scenario.machine_id
        }
        refs.update(
            {
                event.id: f"EV-{200000 + index * 1000 + number:06d}"
                for number, event in enumerate(dataset.events_for(scenario.machine_id))
                if event.timestamp >= scenario.onset
            }
        )
        refs.update(
            {
                entry.id: f"LB-{20000 + index * 1000 + number:05d}"
                for number, entry in enumerate(dataset.logbook_for(scenario.machine_id))
            }
        )
        copied.append(
            scenario.model_copy(
                update={
                    "machine_id": machine_id,
                    "decisive_refs": tuple(refs[ref] for ref in scenario.decisive_refs),
                }
            )
        )
    return tuple(copied)


def extend_feedback_seed(dataset: DiagnosticsDataset) -> DiagnosticsDataset:
    """Clone four clean incidents onto new machines without changing existing records."""
    machines = list(dataset.machines)
    telemetry = list(dataset.telemetry)
    events = list(dataset.error_events)
    logbook = list(dataset.logbook)
    for index, scenario in enumerate(dataset.scenarios[:4]):
        machine_id = f"M-{53 + index:04d}"
        machines.append(dataset.machine(scenario.machine_id).model_copy(update={"id": machine_id}))
        telemetry.extend(
            series.model_copy(update={"machine_id": machine_id})
            for series in dataset.telemetry
            if series.machine_id == scenario.machine_id
        )
        events.extend(
            event.model_copy(
                update={
                    "id": f"EV-{200000 + index * 1000 + number:06d}",
                    "machine_id": machine_id,
                    "code": "EC-9901",
                }
            )
            for number, event in enumerate(dataset.events_for(scenario.machine_id))
            if event.timestamp >= scenario.onset
        )
        logbook.extend(
            entry.model_copy(
                update={
                    "id": f"LB-{20000 + index * 1000 + number:05d}",
                    "machine_id": machine_id,
                }
            )
            for number, entry in enumerate(dataset.logbook_for(scenario.machine_id))
        )
    return dataset.model_copy(
        update={
            "machines": tuple(machines),
            "telemetry": tuple(telemetry),
            "error_events": tuple(events),
            "logbook": tuple(logbook),
            "error_codes": (
                *dataset.error_codes,
                ErrorCode(
                    code="EC-9901",
                    subsystem=Subsystem.CONTROLLER,
                    severity=Severity.WARNING,
                    description="Unmapped diagnostic event; correlate telemetry and service clues.",
                ),
            ),
        }
    )
