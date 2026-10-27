"""Tool logic behind the MCP server, independent of the Functions runtime.

Every record returned carries a ``ref`` that an agent can cite as evidence and an evaluator
can resolve: error events ``EV-...``, logbook entries ``LB-...``, telemetry
``TS:<machine>:<signal>``, error codes ``EC-...``.

"Now" is the dataset's reference time, so the synthetic incidents stay current.
"""

import statistics
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from diagnostics_domain.dataset import DiagnosticsDataset, UnknownRecordError, load_seed
from diagnostics_domain.models import Severity, Subsystem

if TYPE_CHECKING:
    from collections.abc import Callable

TOOL_NAMES = (
    "get_machine_context",
    "get_error_events",
    "get_telemetry_window",
    "lookup_error_code",
    "get_logbook",
)
"""The MCP tool names this server exposes; agents' instructions refer to them."""

MAX_EVENT_HOURS = 168
MAX_TELEMETRY_HOURS = 168
MAX_LOGBOOK_DAYS = 120
MAX_EVENTS = 100
SUMMARY_POINTS = 12


class ToolError(ValueError):
    """An invalid tool call; the message is safe to show to the calling agent."""


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class SignalInfo(_Result):
    name: str
    unit: str
    subsystem: Subsystem
    nominal: float
    tolerance: float


class MachineContext(_Result):
    machine_id: str
    platform: str
    site: str
    install_date: str
    software_release: str
    last_software_update: str
    reference_time: datetime
    signals: list[SignalInfo]


class CodeSummary(_Result):
    ref: str
    description: str
    severity: Severity
    subsystem: Subsystem
    count: int
    first_seen: datetime
    last_seen: datetime


class EventItem(_Result):
    ref: str
    timestamp: datetime
    code: str
    message: str


class ErrorEvents(_Result):
    machine_id: str
    window_start: datetime
    window_end: datetime
    summary: list[CodeSummary]
    events: list[EventItem]
    truncated: bool


class Sample(_Result):
    timestamp: datetime
    value: float


class TelemetryWindow(_Result):
    ref: str
    machine_id: str
    signal: str
    unit: str
    nominal: float
    tolerance: float
    window_start: datetime
    window_end: datetime
    baseline_mean: float
    recent_mean: float
    recent_stdev: float
    minimum: float
    maximum: float
    trend_per_day: float
    out_of_tolerance_count: int
    first_out_of_tolerance: datetime | None
    samples: list[Sample]


class PossibleCause(_Result):
    failure_mode_id: str
    name: str
    subsystem: Subsystem
    recommended_checks: list[str]


class ErrorCodeReference(_Result):
    ref: str
    description: str
    severity: Severity
    subsystem: Subsystem
    possible_causes: list[PossibleCause]


class LogbookItem(_Result):
    ref: str
    timestamp: datetime
    author_role: str
    text: str


class Logbook(_Result):
    machine_id: str
    window_start: datetime
    window_end: datetime
    entries: list[LogbookItem]


def telemetry_ref(machine_id: str, signal: str) -> str:
    return f"TS:{machine_id}:{signal}"


class DiagnosticsTools:
    def __init__(self, dataset: DiagnosticsDataset) -> None:
        self._data = dataset

    @classmethod
    def from_seed(cls) -> DiagnosticsTools:
        return cls(load_seed())

    @property
    def now(self) -> datetime:
        return self._data.reference_time

    def machine_context(self, machine_id: str) -> MachineContext:
        machine = self._lookup(lambda: self._data.machine(machine_id))
        return MachineContext(
            machine_id=machine.id,
            platform=machine.platform,
            site=machine.site,
            install_date=machine.install_date.isoformat(),
            software_release=machine.software_release,
            last_software_update=machine.last_software_update.isoformat(),
            reference_time=self.now,
            signals=[
                SignalInfo(
                    name=s.name,
                    unit=s.unit,
                    subsystem=s.subsystem,
                    nominal=s.nominal,
                    tolerance=s.tolerance,
                )
                for s in self._data.signals
            ],
        )

    def error_events(
        self, machine_id: str, hours: int = 48, include_info: bool = False
    ) -> ErrorEvents:
        _check_range("hours", hours, 1, MAX_EVENT_HOURS)
        start = self.now - timedelta(hours=hours)
        events = self._lookup(lambda: self._data.events_for(machine_id, start, self.now))
        if not include_info:
            events = [
                e for e in events if self._data.error_code(e.code).severity is not Severity.INFO
            ]

        summary: list[CodeSummary] = []
        for code in sorted({e.code for e in events}):
            matching = [e for e in events if e.code == code]
            reference = self._data.error_code(code)
            summary.append(
                CodeSummary(
                    ref=code,
                    description=reference.description,
                    severity=reference.severity,
                    subsystem=reference.subsystem,
                    count=len(matching),
                    first_seen=matching[0].timestamp,
                    last_seen=matching[-1].timestamp,
                )
            )
        summary.sort(key=lambda s: (-s.count, s.ref))

        recent = events[-MAX_EVENTS:]
        return ErrorEvents(
            machine_id=machine_id,
            window_start=start,
            window_end=self.now,
            summary=summary,
            events=[
                EventItem(ref=e.id, timestamp=e.timestamp, code=e.code, message=e.message)
                for e in recent
            ],
            truncated=len(events) > len(recent),
        )

    def telemetry_window(
        self, machine_id: str, signal: str, hours: int = 72, sample_every_hours: int = 6
    ) -> TelemetryWindow:
        _check_range("hours", hours, SUMMARY_POINTS * 2, MAX_TELEMETRY_HOURS)
        _check_range("sample_every_hours", sample_every_hours, 1, 24)
        start = self.now - timedelta(hours=hours)
        series = self._lookup(lambda: self._data.telemetry_for(machine_id, signal, start, self.now))
        spec = self._data.signal(signal)
        values = series.values
        step = timedelta(minutes=series.interval_minutes)
        times = [series.start + i * step for i in range(len(values))]

        outside = [
            t for t, v in zip(times, values, strict=True) if abs(v - spec.nominal) > spec.tolerance
        ]
        days = [(t - times[0]) / timedelta(days=1) for t in times]
        slope, _ = statistics.linear_regression(days, values)
        stride = max(1, timedelta(hours=sample_every_hours) // step)
        recent = values[-SUMMARY_POINTS:]

        return TelemetryWindow(
            ref=telemetry_ref(machine_id, signal),
            machine_id=machine_id,
            signal=signal,
            unit=series.unit,
            nominal=spec.nominal,
            tolerance=spec.tolerance,
            window_start=times[0],
            window_end=times[-1],
            baseline_mean=_r(statistics.fmean(values[:SUMMARY_POINTS])),
            recent_mean=_r(statistics.fmean(recent)),
            recent_stdev=_r(statistics.pstdev(recent)),
            minimum=min(values),
            maximum=max(values),
            trend_per_day=_r(slope),
            out_of_tolerance_count=len(outside),
            first_out_of_tolerance=outside[0] if outside else None,
            samples=[
                Sample(timestamp=t, value=v)
                for t, v in list(zip(times, values, strict=True))[::stride]
            ],
        )

    def error_code(self, code: str) -> ErrorCodeReference:
        reference = self._lookup(lambda: self._data.error_code(code))
        return ErrorCodeReference(
            ref=reference.code,
            description=reference.description,
            severity=reference.severity,
            subsystem=reference.subsystem,
            possible_causes=[
                PossibleCause(
                    failure_mode_id=mode.id,
                    name=mode.name,
                    subsystem=mode.subsystem,
                    recommended_checks=list(mode.recommended_checks),
                )
                for mode in self._data.failure_modes
                if code in mode.error_codes
            ],
        )

    def logbook(self, machine_id: str, days: int = 30) -> Logbook:
        _check_range("days", days, 1, MAX_LOGBOOK_DAYS)
        start = self.now - timedelta(days=days)
        entries = self._lookup(lambda: self._data.logbook_for(machine_id))
        return Logbook(
            machine_id=machine_id,
            window_start=start,
            window_end=self.now,
            entries=[
                LogbookItem(ref=e.id, timestamp=e.timestamp, author_role=e.author_role, text=e.text)
                for e in entries
                if start <= e.timestamp <= self.now
            ],
        )

    @staticmethod
    def _lookup[T](fetch: Callable[[], T]) -> T:
        try:
            return fetch()
        except UnknownRecordError as error:
            raise ToolError(str(error)) from error


def _check_range(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise ToolError(f"{name} must be between {low} and {high}, got {value}")


def _r(value: float) -> float:
    return round(value, 4)
