"""The complete synthetic dataset plus the lookups tools need."""

from datetime import datetime, timedelta
from functools import cache
from importlib import resources

from pydantic import BaseModel, ConfigDict

from diagnostics_domain.models import (
    ErrorCode,
    ErrorEvent,
    FailureMode,
    HistoricalCase,
    LogbookEntry,
    Machine,
    Scenario,
    Signal,
    TelemetrySeries,
)

SEED_RESOURCE = "data/seed.json"


class UnknownRecordError(LookupError):
    """Raised when a lookup references an identifier that does not exist."""

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"Unknown {kind}: {key}")
        self.kind = kind
        self.key = key


class DiagnosticsDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference_time: datetime
    signals: tuple[Signal, ...]
    error_codes: tuple[ErrorCode, ...]
    failure_modes: tuple[FailureMode, ...]
    machines: tuple[Machine, ...]
    error_events: tuple[ErrorEvent, ...]
    telemetry: tuple[TelemetrySeries, ...]
    logbook: tuple[LogbookEntry, ...]
    historical_cases: tuple[HistoricalCase, ...]
    scenarios: tuple[Scenario, ...]

    def machine(self, machine_id: str) -> Machine:
        for machine in self.machines:
            if machine.id == machine_id:
                return machine
        raise UnknownRecordError("machine", machine_id)

    def error_code(self, code: str) -> ErrorCode:
        for error_code in self.error_codes:
            if error_code.code == code:
                return error_code
        raise UnknownRecordError("error code", code)

    def failure_mode(self, failure_mode_id: str) -> FailureMode:
        for failure_mode in self.failure_modes:
            if failure_mode.id == failure_mode_id:
                return failure_mode
        raise UnknownRecordError("failure mode", failure_mode_id)

    def signal(self, name: str) -> Signal:
        for signal in self.signals:
            if signal.name == name:
                return signal
        raise UnknownRecordError("signal", name)

    def scenario(self, scenario_id: str) -> Scenario:
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        raise UnknownRecordError("scenario", scenario_id)

    def events_for(
        self,
        machine_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ErrorEvent]:
        """Error events for a machine, ordered by time, optionally within ``[start, end]``."""
        self.machine(machine_id)
        return [
            event
            for event in self.error_events
            if event.machine_id == machine_id
            and (start is None or event.timestamp >= start)
            and (end is None or event.timestamp <= end)
        ]

    def logbook_for(self, machine_id: str) -> list[LogbookEntry]:
        self.machine(machine_id)
        return [entry for entry in self.logbook if entry.machine_id == machine_id]

    def telemetry_for(
        self,
        machine_id: str,
        signal: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> TelemetrySeries:
        """The series for one machine and signal, sliced to ``[start, end]`` if given."""
        self.machine(machine_id)
        self.signal(signal)
        series = next(
            s for s in self.telemetry if s.machine_id == machine_id and s.signal == signal
        )
        step = timedelta(minutes=series.interval_minutes)
        first = 0 if start is None else max(0, _ceil_div(start - series.start, step))
        last = len(series.values) if end is None else (end - series.start) // step + 1
        last = min(len(series.values), max(first, last))
        return series.model_copy(
            update={"start": series.start + first * step, "values": series.values[first:last]}
        )


def _ceil_div(delta: timedelta, step: timedelta) -> int:
    return -(-delta // step)


@cache
def load_seed() -> DiagnosticsDataset:
    """Load the committed seed dataset shipped with this package."""
    raw = resources.files("diagnostics_domain").joinpath(SEED_RESOURCE).read_text("utf-8")
    return DiagnosticsDataset.model_validate_json(raw)
