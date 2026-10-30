"""The five planted recurring failures and their expected downstream ownership."""

from diagnostics_domain.feedback_models import PlantedPattern


def planted_patterns() -> list[PlantedPattern]:
    """Return fresh pattern definitions; membership is filled by the generator."""
    return [
        PlantedPattern(
            id="vacuum_telemetry_omission",
            description="Vacuum faults diagnosed without checking pressure telemetry.",
            classification="missed_evidence",
            route="learner",
            episode_ids=[],
        ),
        PlantedPattern(
            id="overlapping_codes_after_update",
            description="Shared error codes outrank decisive telemetry after a software update.",
            classification="wrong_ranking",
            route="learner",
            episode_ids=[],
        ),
        PlantedPattern(
            id="missing_code_mapping",
            description="An unmapped error code leaves a supported failure mode unknown.",
            classification="knowledge_gap",
            route="knowledge",
            episode_ids=[],
        ),
        PlantedPattern(
            id="data_quality",
            description="Missing, duplicate or late telemetry is mistaken for a physical fault.",
            classification="data_quality",
            route="backlog",
            episode_ids=[],
        ),
        PlantedPattern(
            id="injection_followed",
            description="Instructions embedded in logbook data override the diagnostic procedure.",
            classification="instruction_followed",
            route="learner",
            episode_ids=[],
        ),
    ]
