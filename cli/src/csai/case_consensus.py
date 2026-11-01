"""Independent, reliability-weighted reviewer admission without generator truth."""

import math
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from cs_platform.episodes import Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from diagnostics_domain.feedback_models import Review


class ConsensusDecision(BaseModel):
    """Recomputed consensus, checked against the report by the promotion adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["admit", "expert", "wait", "reject"]
    reason: str
    verdict: Verdict | None
    failure_mode: str | None
    agreement: float
    independent_reviewers: int
    root_cause_support: float
    notes: list[str]
    supporting_review_ids: list[str]


def reviewer_identity(review: Review) -> str:
    """Normalize named identities; anonymous rows never establish consensus."""
    return (review.feedback.reviewer or "").strip().casefold() or "(anonymous)"


def review_consensus(
    reviews: Sequence[Review],
    *,
    episode_id: str,
    source_review_ids: Sequence[str],
    reviewer_weights: Mapping[str, float],
) -> ConsensusDecision:
    """Reproduce cohort-weighted consensus using one retained vote per identity."""
    empty = ConsensusDecision(
        status="reject",
        reason="Inconsistent source review evidence",
        verdict=None,
        failure_mode=None,
        agreement=0,
        independent_reviewers=len(reviews),
        root_cause_support=0,
        notes=[],
        supporting_review_ids=[],
    )
    ids = [row.id for row in reviews]
    identities = [reviewer_identity(row) for row in reviews]
    if (
        len(ids) != len(set(ids))
        or any(not row_id.strip() for row_id in ids)
        or len(identities) != len(set(identities))
        or len(source_review_ids) != len(set(source_review_ids))
        or set(ids) != set(source_review_ids)
        or any(row.episode_id != episode_id or row.source != "synthetic" for row in reviews)
        or any(
            identity not in reviewer_weights
            or not math.isfinite(reviewer_weights[identity])
            or not 0 < reviewer_weights[identity] < 1
            for identity in identities
        )
    ):
        return empty
    if not reviews:
        return empty.model_copy(update={"status": "wait", "reason": "No independent reviews"})
    weights: dict[str, float] = defaultdict(float)
    for row in sorted(reviews, key=reviewer_identity):
        weights[row.feedback.verdict.value] += reviewer_weights[reviewer_identity(row)]
    winner = max(weights, key=lambda verdict: weights[verdict])
    supporters = [
        row
        for row in reviews
        if row.feedback.verdict.value == winner and reviewer_identity(row) != "(anonymous)"
    ]
    agreement = weights[winner] / sum(weights.values())
    accepted = len(supporters) >= 2 and agreement > 0.6
    causes = Counter(
        row.feedback.actual_root_cause.strip()
        for row in supporters
        if row.feedback.actual_root_cause and row.feedback.actual_root_cause.strip()
    )
    cause, count = causes.most_common(1)[0] if causes else (None, 0)
    supported_cause = cause if accepted and count >= 2 and count > len(supporters) / 2 else None
    notes = (
        sorted(
            {
                " ".join(row.feedback.note.split()).casefold()
                for row in supporters
                if row.feedback.note
            }
        )
        if accepted
        else []
    )
    same_cause = [
        row.id
        for row in supporters
        if row.feedback.actual_root_cause
        and row.feedback.actual_root_cause.strip() == supported_cause
    ]
    status: Literal["admit", "expert", "wait", "reject"] = "admit"
    reason = "Independent verdict and root-cause consensus"
    if len([identity for identity in identities if identity != "(anonymous)"]) < 2:
        status, reason = "wait", "At least two independent named reviewers are required"
    elif not accepted or supported_cause is None:
        status, reason = "expert", "Verdict or actual root cause needs expert resolution"
    elif winner == "correct":
        status, reason = "reject", "No recurring failure: reviewers agree the output is correct"
    return ConsensusDecision(
        status=status,
        reason=reason,
        verdict=Verdict(winner) if accepted else None,
        failure_mode=supported_cause,
        agreement=agreement,
        independent_reviewers=len(reviews),
        root_cause_support=count / len(supporters) if supporters else 0,
        notes=notes,
        supporting_review_ids=sorted(same_cause),
    )
