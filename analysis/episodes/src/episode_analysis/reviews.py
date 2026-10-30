"""One independent vote per reviewer and episode; leave-one-out reliability."""

from collections import Counter, defaultdict
from datetime import UTC
from typing import TYPE_CHECKING

from episode_analysis.models import ReviewerAgreement, ReviewSummary

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cs_platform.episodes import Verdict
    from diagnostics_domain.feedback_models import Review


def _reviewer(review: Review) -> str:
    return (review.feedback.reviewer or "").strip().casefold() or "(anonymous)"


def clean_reviews(reviews: Sequence[Review]) -> list[Review]:
    """Collapse semantic duplicates and revisions, regardless of row ID.

    Anonymous feedback is conservatively one voice per episode. Latest revision wins;
    canonical content breaks same-time ties deterministically, not input ordering.
    """
    chosen: dict[tuple[str, str], Review] = {}
    for row in reviews:
        key = (row.episode_id, _reviewer(row))
        previous = chosen.get(key)
        if previous is None or _order(row) > _order(previous):
            chosen[key] = row
    return [chosen[key] for key in sorted(chosen)]


def _order(review: Review) -> tuple[float, str, tuple[str, str, str]]:
    feedback = review.feedback
    raw = (
        feedback.verdict.value,
        feedback.actual_root_cause or "",
        feedback.note or "",
    )
    semantic = "|".join(" ".join(part.split()).casefold() for part in raw)
    submitted = feedback.submitted_at
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=UTC)
    return submitted.timestamp(), semantic, raw


def _majority(values: list[Verdict]) -> Verdict | None:
    counts = Counter(values)
    if not counts:
        return None
    winner, count = counts.most_common(1)[0]
    return winner if count > len(values) / 2 else None


def summarize(
    reviews: Sequence[Review],
) -> tuple[dict[str, ReviewSummary], dict[str, ReviewerAgreement]]:
    """Estimate reliability from other reviewers, then form conservative consensus."""
    groups: dict[str, list[Review]] = defaultdict(list)
    for row in clean_reviews(reviews):
        groups[row.episode_id].append(row)
    comparisons: Counter[str] = Counter()
    agreements: Counter[str] = Counter()
    for rows in groups.values():
        for row in rows:
            others = [other.feedback.verdict for other in rows if other is not row]
            majority = _majority(others) if len(others) >= 2 else None
            if majority is not None:
                reviewer = _reviewer(row)
                comparisons[reviewer] += 1
                agreements[reviewer] += row.feedback.verdict == majority
    metrics = {
        _reviewer(row): ReviewerAgreement(
            comparisons=comparisons[_reviewer(row)],
            agreements=agreements[_reviewer(row)],
            reliability=(agreements[_reviewer(row)] + 1) / (comparisons[_reviewer(row)] + 2),
        )
        for rows in groups.values()
        for row in rows
    }
    results: dict[str, ReviewSummary] = {}
    for episode_id, rows in groups.items():
        weights: dict[Verdict, float] = defaultdict(float)
        for row in rows:
            weights[row.feedback.verdict] += metrics[_reviewer(row)].reliability
        winner = max(weights, key=lambda verdict: weights[verdict])
        supporters = [row for row in rows if row.feedback.verdict == winner]
        agreement = weights[winner] / sum(weights.values())
        # A single strict reviewer, repetitions, ties and anonymous feedback cannot
        # establish a failure or a reference answer.
        trusted = [row for row in supporters if _reviewer(row) != "(anonymous)"]
        accepted = len(trusted) >= 2 and agreement > 0.6
        causes: Counter[str] = Counter()
        for row in trusted:
            cause = row.feedback.actual_root_cause
            if cause:
                causes[cause.strip()] += 1
        cause, count = causes.most_common(1)[0] if causes else (None, 0)
        results[episode_id] = ReviewSummary(
            episode_id=episode_id,
            verdict=winner.value if accepted else None,
            agreement=agreement,
            independent_reviewers=len(rows),
            notes=sorted(
                {
                    " ".join(row.feedback.note.split()).casefold()
                    for row in trusted
                    if row.feedback.note
                }
            )
            if accepted
            else [],
            expected_mode=cause if accepted and count >= 2 and count > len(trusted) / 2 else None,
            root_cause_support=count / len(trusted) if trusted else 0,
        )
    return results, metrics
