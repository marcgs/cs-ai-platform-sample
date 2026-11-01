"""Closed observational vocabulary, independent of generator membership and answer keys."""

import hashlib
import re
from typing import Literal, get_args

from pydantic import TypeAdapter

type Category = Literal[
    "missed_evidence",
    "wrong_ranking",
    "knowledge_gap",
    "data_quality",
    "tool_error",
    "ambiguous_input",
    "instruction_followed",
]
type Condition = Literal[
    "stage_cooling_drift",
    "chamber_vacuum_leak",
    "source_energy_instability",
    "reticle_gripper_wear",
    "interferometer_contamination",
    "controller_firmware_regression",
    "purge_flow_restriction",
    "lens_heating_drift",
    "pressure_sensor_fault",
    "pressure_telemetry",
    "temperature_history",
    "shared_codes_after_software_update",
    "unmapped_error_code",
    "incomplete_duplicate_late_telemetry",
    "prompt_injection_logbook",
    "failed_diagnostic_tool",
    "insufficient_discriminating_evidence",
]

# Catalog FM-01..FM-09 mechanisms and signals, plus the observational failure taxonomy.
# These are not generated pattern memberships or expected answers.
CONDITIONS: dict[Condition, str] = {
    "stage_cooling_drift": "FM-01 mechanism: stage coolant temperature drift.",
    "chamber_vacuum_leak": "FM-02 mechanism: physical chamber pressure leak.",
    "source_energy_instability": "FM-03 mechanism: unstable source pulse energy.",
    "reticle_gripper_wear": "FM-04 mechanism: degrading handler grip force.",
    "interferometer_contamination": "FM-05 mechanism: increasing interferometer noise.",
    "controller_firmware_regression": "FM-06 mechanism: controller regression and CPU load.",
    "purge_flow_restriction": "FM-07 mechanism: restricted purge gas flow.",
    "lens_heating_drift": "FM-08 mechanism: thermal focus offset drift.",
    "pressure_sensor_fault": "FM-09 mechanism: pressure sensor disagrees with reference.",
    "pressure_telemetry": "Chamber pressure evidence absent or unused, not a confirmed leak.",
    "temperature_history": "Stage coolant temperature evidence absent or unused.",
    "shared_codes_after_software_update": "Shared codes outweigh discriminating update evidence.",
    "unmapped_error_code": "Observed code has no usable knowledge mapping.",
    "incomplete_duplicate_late_telemetry": "Missing, duplicate or late telemetry source records.",
    "prompt_injection_logbook": "Instructions in logbook data override the diagnostic procedure.",
    "failed_diagnostic_tool": "A diagnostic call fails or returns an explicit error.",
    "insufficient_discriminating_evidence": "Successful evidence remains genuinely inconclusive.",
}

_ALIASES = {
    "diagnosis_without_pressure_telemetry": "pressure_telemetry",
    "vacuum_telemetry_omission": "pressure_telemetry",
    "prompt_injection_in_logbook": "prompt_injection_logbook",
    "logbook_instruction_overrode_procedure": "prompt_injection_logbook",
    "untrusted_logbook": "prompt_injection_logbook",
    "overlapping_codes_after_update": "shared_codes_after_software_update",
    "missing_code_mapping": "unmapped_error_code",
}


def canonical_condition(value: str) -> Condition:
    """Normalize spelling and explicit legacy aliases; reject unrecognized mechanisms."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return TypeAdapter(Condition).validate_python(_ALIASES.get(slug, slug))


def cluster_key(category: Category, condition: str) -> str:
    """Content-derived identity; independent of rationale, ranking and member order."""
    if category not in get_args(Category.__value__):
        raise ValueError(f"Unknown cluster category: {category}")
    canonical = canonical_condition(condition)
    return hashlib.sha256(f"{category}:{canonical}".encode()).hexdigest()[:16]
