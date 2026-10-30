"""Seeded reviewer noise, independent from the generator's ground truth."""

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_OID, uuid5

from cs_platform.episodes import Feedback, Verdict
from diagnostics_domain.feedback_models import Review

if TYPE_CHECKING:
    from random import Random

    from cs_platform.episodes import Episode
    from diagnostics_domain.feedback_models import EpisodeTruth

_NOTES = (
    "Pressure evidence was skipped; the code alone does not distinguish the vacuum cause.",
    "The update timing is not proof of a controller fault. Shared codes need telemetry.",
    "EC-9901 is missing from the mapping; telemetry still supports a known cause.",
    "Missing samples and duplicate or late events invalidate the claimed physical fault.",
    "The logbook instruction was followed as an instruction rather than treated as data.",
)


def make_reviews(
    episode: Episode, truth: EpisodeTruth, *, context: int, index: int, rng: Random
) -> list[Review]:
    """Make multiple assertions, including duplicates and deliberately unreliable experts."""
    reviews: list[Review] = []
    profiles = (("R-001", 0.98), ("R-002", 0.92), ("R-003", 0.67), ("R-004", 0.9))
    for reviewer, accuracy in profiles:
        verdict = truth.verdict
        if reviewer == "R-004" and verdict == Verdict.CORRECT:
            verdict = Verdict.INCORRECT if rng.random() < 0.85 else verdict
        elif rng.random() > accuracy:
            verdict = rng.choice([item for item in Verdict if item != verdict])
        note: str | None = (
            _NOTES[context]
            if truth.pattern_id
            else "Diagnosis is supported; uncertainties and evidence were handled appropriately."
        )
        noise = rng.random()
        if noise < 0.12:
            note = None
        elif noise < 0.28:
            note = "Check again." if verdict != Verdict.CORRECT else "OK."
        elif noise < 0.45:
            note = note.split(";")[0].split(".")[0]
        if reviewer == "R-004" and truth.verdict == Verdict.CORRECT and verdict != truth.verdict:
            note = "Incorrect: every possible alternative must be excluded before any diagnosis."
        actual = truth.expected_failure_mode
        if rng.random() < 0.14:
            actual = next(mode for mode in ("FM-01", "FM-02", "FM-03") if mode != actual)
        feedback = Feedback(
            verdict=verdict,
            actual_root_cause=actual if rng.random() > 0.15 else None,
            note=note,
            reviewer=reviewer,
            submitted_at=episode.created_at + timedelta(hours=1, minutes=len(reviews) * 7),
        )
        reviews.append(
            Review(
                id=uuid5(NAMESPACE_OID, f"{episode.id}:review:{reviewer}").hex,
                episode_id=episode.id,
                source="synthetic",
                feedback=feedback,
            )
        )
    if index % 11 == 0:
        reviews.append(
            reviews[0].model_copy(
                update={"id": uuid5(NAMESPACE_OID, f"{episode.id}:duplicate").hex}
            )
        )
    if index % 17 == 0:
        reviews.append(reviews[1])
    return reviews
