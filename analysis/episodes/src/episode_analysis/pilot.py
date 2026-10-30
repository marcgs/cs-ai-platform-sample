"""Small deterministic pilot selection using observations, never answer keys."""

import hashlib
from typing import TYPE_CHECKING

from cs_platform.episode_io import export_episodes
from episode_analysis.models import Record
from episode_analysis.pipeline import prepare

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from cs_platform.episodes import Episode
    from diagnostics_domain.feedback_models import Review


class Pilot(Record):
    seed: str
    episode_ids: list[str]
    selected_misses: int
    selected_comparisons: int
    candidate_count: int
    limitations: list[str]


def sample(
    episodes: Sequence[Episode],
    reviews: Sequence[Review],
    *,
    misses: int,
    controls: int,
    seed: str,
    output: Path,
) -> Pilot:
    """Write an isolated cohort of consensus misses and noncandidate comparisons.

    Comparisons are not asserted correct: disagreement can hide genuine misses.
    Reliability is recalculated on the cohort, so preflight remains authoritative.
    """
    if misses < 1 or controls < 1:
        raise ValueError("A pilot requires positive miss and comparison counts")
    prepared = prepare(episodes, reviews)
    candidates = {item.episode.id for item in prepared.candidates}
    comparisons = set(prepared.episode_ids) - candidates
    if misses > len(candidates) or controls > len(comparisons):
        raise ValueError("Requested pilot strata exceed the available population")

    def order(episode_id: str) -> tuple[str, str]:
        digest = hashlib.sha256(f"{seed}:{episode_id}".encode()).hexdigest()
        return digest, episode_id

    selected = set(sorted(candidates, key=order)[:misses])
    selected.update(sorted(comparisons, key=order)[:controls])
    unique = {episode.id: episode for episode in episodes}
    cohort = [unique[episode_id] for episode_id in sorted(selected, key=order)]
    cohort_reviews = sorted(
        (review for review in reviews if review.episode_id in selected),
        key=lambda review: (review.episode_id, review.id, review.model_dump_json()),
    )
    result = Pilot(
        seed=seed,
        episode_ids=[episode.id for episode in cohort],
        selected_misses=misses,
        selected_comparisons=controls,
        candidate_count=len(prepare(cohort, cohort_reviews).candidates),
        limitations=[
            "Strata use reviewer consensus, not generator truth or classifier labels.",
            "Comparisons include correct and uncertain episodes, not verified negatives.",
            "Cohort reliability is recalculated; estimate the selected files before labeling.",
            "Reserve the generation seed before inspection; do not optimize the selection.",
        ],
    )
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Pilot output must be empty; never mix populations")
    output.mkdir(parents=True, exist_ok=True)
    export_episodes(cohort, output / "episodes.jsonl", source=cohort[0].source)
    (output / "reviews.jsonl").write_text(
        "".join(review.model_dump_json() + "\n" for review in cohort_reviews), encoding="utf-8"
    )
    (output / "selection.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
