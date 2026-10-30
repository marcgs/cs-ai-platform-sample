"""Enrich only from observed context, reviewer consensus and historical cases."""

import re
from statistics import mean
from typing import TYPE_CHECKING

from pydantic import JsonValue, TypeAdapter

from episode_analysis.models import EnrichedEpisode

if TYPE_CHECKING:
    from cs_platform.episodes import Episode
    from diagnostics_domain.dataset import DiagnosticsDataset
    from episode_analysis.models import ReviewSummary


def enrich(
    episode: Episode, review: ReviewSummary, dataset: DiagnosticsDataset | None
) -> EnrichedEpisode:
    """Keep unknown context unknown; do not consult scenarios or any answer key."""
    context: dict[str, object] = {}
    for call in episode.tool_calls:
        if call.name.split("___")[-1] == "get_machine_context" and call.result:
            try:
                raw = TypeAdapter(dict[str, JsonValue]).validate_json(call.result)
            except ValueError:
                continue
            context = dict(raw)
            break
    match = re.search(r"\bM-\d{4}\b", episode.input)
    machine_id = _string(context.get("id")) or (match.group() if match else None)
    platform = _string(context.get("platform"))
    release = _string(context.get("software_release"))
    if dataset and machine_id:
        machine = next((item for item in dataset.machines if item.id == machine_id), None)
        if machine:
            platform = platform or machine.platform
            release = release or machine.software_release
    expected = review.expected_mode
    histories = dataset.historical_cases if dataset else ()
    matching = [
        case.downtime_hours for case in histories if case.confirmed_failure_mode == expected
    ]
    all_hours = [case.downtime_hours for case in histories]
    return EnrichedEpisode(
        episode=episode.model_copy(update={"feedback": None}),
        review=review,
        machine_id=machine_id,
        platform=platform,
        software_release=release,
        expected_failure_mode=expected,
        expected_mode_basis="reviewer_consensus" if expected else "unknown",
        downtime_hours=mean(matching or all_hours) if all_hours else 0,
        impact_basis="historical_mode_mean"
        if matching
        else "historical_population_mean"
        if all_hours
        else "unavailable",
    )


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
