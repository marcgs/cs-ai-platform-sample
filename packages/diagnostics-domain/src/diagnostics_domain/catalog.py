"""Static reference data: telemetry signals, error codes and failure modes.

Several error codes are deliberately shared between failure modes (e.g. ``EC-2104`` overlay
correction limit). An agent therefore cannot map codes to a root cause one-to-one and must
use telemetry and logbook evidence to discriminate between hypotheses.
"""

from diagnostics_domain.models import (
    ErrorCode,
    FailureMode,
    Severity,
    Signal,
    SignatureKind,
    Subsystem,
    TelemetrySignature,
)

# Keep the legacy catalogs separate: their order also drives the original seeded stream.
ADDITIONAL_SIGNALS = (
    Signal(
        name="chamber_pressure_reference_pa",
        unit="Pa",
        subsystem=Subsystem.VACUUM,
        nominal=0.50,
        noise=0.005,
        tolerance=0.10,
    ),
)
ADDITIONAL_ERROR_CODES = (
    ErrorCode(
        code="EC-7201",
        subsystem=Subsystem.VACUUM,
        severity=Severity.WARNING,
        description="Primary and independent pressure sensors disagree",
    ),
    ErrorCode(
        code="EC-7901",
        subsystem=Subsystem.CONTROLLER,
        severity=Severity.WARNING,
        description="Unmapped intermittent timing residual; no validated catalog cause",
    ),
)
ADDITIONAL_FAILURE_MODES = (
    FailureMode(
        id="FM-09",
        name="Pressure sensor measurement fault",
        subsystem=Subsystem.VACUUM,
        root_cause="The primary pressure sensor is stuck or drifting; chamber pressure is healthy.",
        error_codes=("EC-7201",),
        signature=TelemetrySignature(
            signal="chamber_pressure_pa", kind=SignatureKind.LEVEL_UP, magnitude=0.35
        ),
        symptoms=("Pressure display disagrees with the independent reference gauge.",),
        recommended_checks=(
            "Compare primary and independent pressure gauges.",
            "Test the primary sensor against a calibrated reference.",
        ),
        logbook_clues=("Independent reference gauge remains stable during primary excursions.",),
    ),
)

SIGNALS: tuple[Signal, ...] = (
    Signal(
        name="stage_coolant_temp_c",
        unit="degC",
        subsystem=Subsystem.WAFER_STAGE,
        nominal=22.0,
        noise=0.02,
        tolerance=0.15,
    ),
    Signal(
        name="chamber_pressure_pa",
        unit="Pa",
        subsystem=Subsystem.VACUUM,
        nominal=0.50,
        noise=0.01,
        tolerance=0.10,
    ),
    Signal(
        name="source_pulse_energy_mj",
        unit="mJ",
        subsystem=Subsystem.LIGHT_SOURCE,
        nominal=10.0,
        noise=0.05,
        tolerance=0.40,
    ),
    Signal(
        name="handler_grip_force_n",
        unit="N",
        subsystem=Subsystem.RETICLE_HANDLING,
        nominal=12.0,
        noise=0.05,
        tolerance=1.0,
    ),
    Signal(
        name="interferometer_noise_nm",
        unit="nm",
        subsystem=Subsystem.METROLOGY,
        nominal=0.30,
        noise=0.01,
        tolerance=0.15,
    ),
    Signal(
        name="controller_cpu_load_pct",
        unit="%",
        subsystem=Subsystem.CONTROLLER,
        nominal=45.0,
        noise=2.0,
        tolerance=30.0,
    ),
    Signal(
        name="purge_gas_flow_slm",
        unit="slm",
        subsystem=Subsystem.GAS_SUPPLY,
        nominal=30.0,
        noise=0.20,
        tolerance=3.0,
    ),
    Signal(
        name="focus_offset_nm",
        unit="nm",
        subsystem=Subsystem.PROJECTION_OPTICS,
        nominal=0.0,
        noise=0.50,
        tolerance=5.0,
    ),
)

ERROR_CODES: tuple[ErrorCode, ...] = (
    # Benign / informational codes used as background noise.
    ErrorCode(
        code="EC-0001",
        subsystem=Subsystem.CONTROLLER,
        severity=Severity.INFO,
        description="Lot started",
    ),
    ErrorCode(
        code="EC-0002",
        subsystem=Subsystem.CONTROLLER,
        severity=Severity.INFO,
        description="Lot completed",
    ),
    ErrorCode(
        code="EC-0105",
        subsystem=Subsystem.RETICLE_HANDLING,
        severity=Severity.WARNING,
        description="Reticle barcode read retried",
    ),
    ErrorCode(
        code="EC-0210",
        subsystem=Subsystem.METROLOGY,
        severity=Severity.WARNING,
        description="Alignment mark contrast low, fallback mark used",
    ),
    # Fault codes.
    ErrorCode(
        code="EC-2101",
        subsystem=Subsystem.WAFER_STAGE,
        severity=Severity.ERROR,
        description="Wafer stage temperature out of tolerance",
    ),
    ErrorCode(
        code="EC-2104",
        subsystem=Subsystem.WAFER_STAGE,
        severity=Severity.WARNING,
        description="Overlay correction limit reached",
    ),
    ErrorCode(
        code="EC-2202",
        subsystem=Subsystem.METROLOGY,
        severity=Severity.WARNING,
        description="Position measurement noise above threshold",
    ),
    ErrorCode(
        code="EC-3301",
        subsystem=Subsystem.VACUUM,
        severity=Severity.ERROR,
        description="Vacuum pump-down timeout",
    ),
    ErrorCode(
        code="EC-3305",
        subsystem=Subsystem.VACUUM,
        severity=Severity.WARNING,
        description="Chamber pressure excursion",
    ),
    ErrorCode(
        code="EC-3401",
        subsystem=Subsystem.GAS_SUPPLY,
        severity=Severity.WARNING,
        description="Purge gas flow below setpoint",
    ),
    ErrorCode(
        code="EC-4101",
        subsystem=Subsystem.PROJECTION_OPTICS,
        severity=Severity.ERROR,
        description="Focus out of tolerance",
    ),
    ErrorCode(
        code="EC-5102",
        subsystem=Subsystem.LIGHT_SOURCE,
        severity=Severity.WARNING,
        description="Dose instability detected",
    ),
    ErrorCode(
        code="EC-5107",
        subsystem=Subsystem.LIGHT_SOURCE,
        severity=Severity.ERROR,
        description="Pulse energy out of range",
    ),
    ErrorCode(
        code="EC-6201",
        subsystem=Subsystem.RETICLE_HANDLING,
        severity=Severity.WARNING,
        description="Reticle transfer retry",
    ),
    ErrorCode(
        code="EC-6203",
        subsystem=Subsystem.RETICLE_HANDLING,
        severity=Severity.ERROR,
        description="Gripper force below minimum",
    ),
    ErrorCode(
        code="EC-9001",
        subsystem=Subsystem.CONTROLLER,
        severity=Severity.ERROR,
        description="Controller watchdog reset",
    ),
    ErrorCode(
        code="EC-9004",
        subsystem=Subsystem.CONTROLLER,
        severity=Severity.WARNING,
        description="Internal communication timeout",
    ),
)

BACKGROUND_CODES: tuple[str, ...] = ("EC-0001", "EC-0002", "EC-0105", "EC-0210")

FAILURE_MODES: tuple[FailureMode, ...] = (
    FailureMode(
        id="FM-01",
        name="Stage cooling drift",
        subsystem=Subsystem.WAFER_STAGE,
        root_cause="Partially closed or fouled valve in the wafer stage cooling loop "
        "reduces coolant flow, so stage temperature drifts upward.",
        error_codes=("EC-2101", "EC-2104"),
        signature=TelemetrySignature(
            signal="stage_coolant_temp_c", kind=SignatureKind.RAMP_UP, magnitude=0.45
        ),
        symptoms=(
            "Overlay getting worse over the last shifts, stage temperature alarm this morning.",
            "Recurring stage temperature errors and overlay correction warnings since yesterday.",
        ),
        recommended_checks=(
            "Verify stage cooling loop flow rate against specification.",
            "Inspect cooling loop valves and filters touched during the last maintenance.",
        ),
        logbook_clues=(
            "Preventive maintenance on stage cooling loop: replaced filter cartridge, "
            "valve V3 re-seated.",
        ),
    ),
    FailureMode(
        id="FM-02",
        name="Chamber vacuum leak",
        subsystem=Subsystem.VACUUM,
        root_cause="Degraded O-ring on a chamber access port causes a slow vacuum leak.",
        error_codes=("EC-3301", "EC-3305"),
        signature=TelemetrySignature(
            signal="chamber_pressure_pa", kind=SignatureKind.RAMP_UP, magnitude=0.35
        ),
        symptoms=(
            "Pump-down takes much longer than usual and we saw a pump-down timeout.",
            "Chamber pressure excursions after the access port was opened.",
        ),
        recommended_checks=(
            "Perform helium leak test on chamber access ports.",
            "Inspect and replace access port O-rings.",
        ),
        logbook_clues=(
            "Chamber access port opened for sensor inspection, port closed afterwards.",
        ),
    ),
    FailureMode(
        id="FM-03",
        name="Light source energy instability",
        subsystem=Subsystem.LIGHT_SOURCE,
        root_cause="Aging light source module produces unstable pulse energy.",
        error_codes=("EC-5102", "EC-5107"),
        signature=TelemetrySignature(
            signal="source_pulse_energy_mj", kind=SignatureKind.NOISE_UP, magnitude=8.0
        ),
        symptoms=(
            "Dose instability warnings and occasional pulse energy errors during exposure.",
            "CD uniformity complaints from the fab, dose warnings in the event log.",
        ),
        recommended_checks=(
            "Review light source module pulse counter against its service interval.",
            "Run light source energy stability diagnostic.",
        ),
        logbook_clues=("Light source module pulse counter at 92% of service interval.",),
    ),
    FailureMode(
        id="FM-04",
        name="Reticle gripper wear",
        subsystem=Subsystem.RETICLE_HANDLING,
        root_cause="Worn gripper pads on the reticle handler reduce grip force.",
        error_codes=("EC-6201", "EC-6203"),
        signature=TelemetrySignature(
            signal="handler_grip_force_n", kind=SignatureKind.RAMP_DOWN, magnitude=2.0
        ),
        symptoms=(
            "Reticle transfer retries piling up, one gripper force error.",
            "Reticle exchange is slow and keeps retrying.",
        ),
        recommended_checks=(
            "Measure gripper force with calibration tool.",
            "Inspect gripper pads for wear and replace if below specification.",
        ),
        logbook_clues=(
            "Reticle handler cycle count approaching gripper pad replacement interval.",
        ),
    ),
    FailureMode(
        id="FM-05",
        name="Interferometer contamination",
        subsystem=Subsystem.METROLOGY,
        root_cause="Contamination on an interferometer mirror increases position measurement "
        "noise.",
        error_codes=("EC-2202", "EC-2104"),
        signature=TelemetrySignature(
            signal="interferometer_noise_nm", kind=SignatureKind.RAMP_UP, magnitude=0.30
        ),
        symptoms=(
            "Overlay correction warnings and position measurement noise warnings.",
            "Overlay drifting, metrology reports noisy position measurement.",
        ),
        recommended_checks=(
            "Inspect interferometer mirrors for contamination.",
            "Run position measurement noise diagnostic.",
        ),
        logbook_clues=(
            "Particle count in the stage compartment slightly elevated after a hood intervention.",
        ),
    ),
    FailureMode(
        id="FM-06",
        name="Controller firmware regression",
        subsystem=Subsystem.CONTROLLER,
        root_cause="A defect in the recently installed controller firmware causes CPU overload "
        "and watchdog resets.",
        error_codes=("EC-9001", "EC-9004"),
        signature=TelemetrySignature(
            signal="controller_cpu_load_pct", kind=SignatureKind.LEVEL_UP, magnitude=40.0
        ),
        symptoms=(
            "Machine rebooted itself twice, communication timeouts before that.",
            "Watchdog resets since the weekend, tool keeps dropping out of production.",
        ),
        recommended_checks=(
            "Compare controller firmware version with known-issue list.",
            "Roll back to previous firmware release if a known issue matches.",
        ),
        logbook_clues=("Controller software updated to the latest release.",),
    ),
    FailureMode(
        id="FM-07",
        name="Purge gas flow restriction",
        subsystem=Subsystem.GAS_SUPPLY,
        root_cause="Clogged purge gas filter restricts flow, causing pressure excursions.",
        error_codes=("EC-3401", "EC-3305"),
        signature=TelemetrySignature(
            signal="purge_gas_flow_slm", kind=SignatureKind.RAMP_DOWN, magnitude=6.0
        ),
        symptoms=(
            "Purge flow low warnings together with pressure excursions.",
            "Pressure excursions in the chamber, purge flow looks lower than normal.",
        ),
        recommended_checks=(
            "Check purge gas filter differential pressure.",
            "Replace purge gas filter if differential pressure exceeds limit.",
        ),
        logbook_clues=("Purge gas filter differential pressure reading noted as high-normal.",),
    ),
    FailureMode(
        id="FM-08",
        name="Lens heating calibration drift",
        subsystem=Subsystem.PROJECTION_OPTICS,
        root_cause="Outdated lens heating calibration causes focus to drift during long "
        "exposure sequences.",
        error_codes=("EC-4101", "EC-2104"),
        signature=TelemetrySignature(
            signal="focus_offset_nm", kind=SignatureKind.RAMP_UP, magnitude=12.0
        ),
        symptoms=(
            "Focus errors toward the end of long lots, overlay warnings as well.",
            "Focus out of tolerance on high-throughput recipes.",
        ),
        recommended_checks=(
            "Check date of last lens heating calibration.",
            "Run lens heating calibration routine.",
        ),
        logbook_clues=(
            "Lens heating calibration skipped during last maintenance due to time constraints.",
        ),
    ),
)
