"""Domain models for the fictional diagnostics fleet.

Everything here is synthetic. Identifiers use fixed prefixes so that evidence cited by an
agent can be traced back to a concrete record:

- machines ``M-0001``, failure modes ``FM-01``, error codes ``EC-1234``,
- error events ``EV-000001``, logbook entries ``LB-00001``, historical cases ``HC-0001``,
- incident scenarios ``SC-001``.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Subsystem(StrEnum):
    WAFER_STAGE = "wafer_stage"
    VACUUM = "vacuum"
    LIGHT_SOURCE = "light_source"
    RETICLE_HANDLING = "reticle_handling"
    METROLOGY = "metrology"
    CONTROLLER = "controller"
    GAS_SUPPLY = "gas_supply"
    PROJECTION_OPTICS = "projection_optics"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SignatureKind(StrEnum):
    """How a failure mode shows up in a telemetry signal after onset."""

    RAMP_UP = "ramp_up"
    RAMP_DOWN = "ramp_down"
    NOISE_UP = "noise_up"
    LEVEL_UP = "level_up"


class Signal(_Record):
    name: str
    unit: str
    subsystem: Subsystem
    nominal: float
    noise: float = Field(gt=0, description="Standard deviation of healthy noise.")
    tolerance: float = Field(gt=0, description="Allowed absolute deviation from nominal.")


class TelemetrySignature(_Record):
    signal: str
    kind: SignatureKind
    magnitude: float = Field(gt=0, description="Deviation reached 48h after onset (or noise x).")


class ErrorCode(_Record):
    code: str
    subsystem: Subsystem
    severity: Severity
    description: str


class FailureMode(_Record):
    id: str
    name: str
    subsystem: Subsystem
    root_cause: str
    error_codes: tuple[str, ...]
    signature: TelemetrySignature
    symptoms: tuple[str, ...] = Field(min_length=1, description="Field-engineer phrasings.")
    recommended_checks: tuple[str, ...]
    logbook_clues: tuple[str, ...] = Field(description="Logbook texts that precede onset.")


class Machine(_Record):
    id: str
    platform: str
    site: str
    install_date: date
    software_release: str
    last_software_update: date


class ErrorEvent(_Record):
    id: str
    machine_id: str
    timestamp: datetime
    code: str
    message: str


class TelemetrySeries(_Record):
    machine_id: str
    signal: str
    unit: str
    start: datetime
    interval_minutes: int = Field(gt=0)
    values: tuple[float, ...]


class LogbookEntry(_Record):
    id: str
    machine_id: str
    timestamp: datetime
    author_role: str
    text: str


class HistoricalCase(_Record):
    id: str
    machine_id: str
    opened: datetime
    symptom: str
    confirmed_failure_mode: str
    resolution: str
    downtime_hours: float


class Scenario(_Record):
    """An active incident: the input a field engineer brings, plus the ground truth."""

    id: str
    machine_id: str
    reported_at: datetime
    symptom: str
    onset: datetime
    expected_failure_mode: str
