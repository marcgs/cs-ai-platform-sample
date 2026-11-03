"""Deterministic promotion of review-backed, replayable feedback candidates."""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from cs_platform.episodes import Episode, ToolCall
from cs_platform.evals import EvalCase, EvalTruth, FeedbackProvenance, assign_splits
from csai.case_consensus import ConsensusDecision, review_consensus, reviewer_identity
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback_replay import replay_episode
from diagnostics_domain.feedback_seed import feedback_scenarios
from episode_analysis.vocabulary import cluster_key
from rca_evals.feedback import case_identity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cs_platform.evals import Category
    from diagnostics_domain.dataset import DiagnosticsDataset
    from episode_analysis.models import Cluster, Report
    from episode_analysis.models import EvalCase as Candidate


class CaseDecision(BaseModel):
    """An explicit admission, duplicate link, wait, expert referral or rejection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster_key: str | None
    episode_id: str
    review_ids: list[str]
    status: Literal["admitted", "duplicate", "wait", "expert", "rejected"]
    reason: str
    case_id: str | None
    consensus: ConsensusDecision | None
    k4: bool


class CaseProposal(BaseModel):
    """Reviewable output; cases remain informational until explicitly governed otherwise."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_sha256: str
    cases: list[EvalCase]
    decisions: list[CaseDecision]
    limitations: list[str]


def report_digest(report: Report) -> str:
    """Hash canonical report content, independent of JSON whitespace and key ordering."""
    return hashlib.sha256(
        json.dumps(
            report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _weights(report: Report) -> dict[str, float]:
    weights: dict[str, float] = {}
    for reviewer, metric in report.reviewer_agreement.items():
        if (
            reviewer != (reviewer.strip().casefold() or "(anonymous)")
            or metric.comparisons < 0
            or not 0 <= metric.agreements <= metric.comparisons <= report.episode_count
            or not math.isfinite(metric.reliability)
            or not math.isclose(
                metric.reliability,
                (metric.agreements + 1) / (metric.comparisons + 2),
                rel_tol=0,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(f"Inconsistent cohort reviewer reliability: {reviewer}")
        weights[reviewer] = metric.reliability
    return weights


def _matches_summary(candidate: Candidate, consensus: ConsensusDecision) -> bool:
    summary = candidate.review_summary
    return (
        summary.episode_id == candidate.episode_id
        and summary.verdict == consensus.verdict
        and summary.expected_mode == consensus.failure_mode
        and summary.independent_reviewers == consensus.independent_reviewers
        and summary.notes == consensus.notes
        and candidate.review_notes == summary.notes
        and candidate.expected_failure_mode == summary.expected_mode
        and candidate.expected_mode_basis
        == ("reviewer_consensus" if summary.expected_mode else "unknown")
        and math.isclose(summary.agreement, consensus.agreement, rel_tol=0, abs_tol=1e-12)
        and math.isclose(
            summary.root_cause_support, consensus.root_cause_support, rel_tol=0, abs_tol=1e-12
        )
    )


def _incident_categories(dataset: DiagnosticsDataset) -> dict[str, set[Category]]:
    categories: dict[str, set[Category]] = defaultdict(set)
    for scenario in (*dataset.scenarios, *feedback_scenarios(dataset)):
        categories[scenario.machine_id].add(scenario.category)
    return categories


def _capture(candidate: Candidate) -> tuple[list[ToolCall], list[str], str | None]:
    if (
        candidate.capture_truncated
        or candidate.capture_status == "running"
        or candidate.capture_completed_at is None
    ):
        return [], [], "K4: Incomplete episode capture"
    if any(
        set(raw) - ToolCall.model_fields.keys()
        or raw.get("replayable") is False
        or raw.get("non_replayable") is True
        for raw in candidate.tool_calls
    ):
        return [], [], "K4: unsupported or explicitly non-replayable capture metadata"
    try:
        calls = [ToolCall.model_validate(raw) for raw in candidate.tool_calls]
    except ValueError:
        return [], [], "K4: malformed tool capture"
    episode = Episode(
        id=candidate.episode_id,
        source="synthetic",
        agent="rca",
        agent_version="feedback-report",
        input=candidate.input,
        tool_calls=calls,
        status=candidate.capture_status,
        created_at=candidate.capture_created_at,
        completed_at=candidate.capture_completed_at,
    )
    replay = replay_episode(episode)
    if not replay.replayable:
        return [], [], "K4: " + "; ".join(issue.reason for issue in replay.issues)
    return calls, replay.fingerprints, None


def _candidate_case(
    candidate: Candidate,
    cluster: Cluster | None,
    consensus: ConsensusDecision,
    categories: dict[str, set[Category]],
    dataset: DiagnosticsDataset,
    calls: list[ToolCall],
    fingerprints: list[str],
) -> tuple[EvalCase | None, str | None]:
    machines = {
        call.arguments["machine_id"]
        for call in calls
        if isinstance(call.arguments.get("machine_id"), str)
    }
    mentioned = set(re.findall(r"\bM-\d{4}\b", candidate.input))
    if len(machines) != 1 or mentioned != machines:
        return None, "Machine identity is missing or inconsistent with the replay input"
    machine = next(iter(machines))
    incident_categories = categories.get(machine, set())
    if len(incident_categories) != 1:
        return None, "Incident category requires expert-supported source metadata"
    mode = consensus.failure_mode
    if (
        mode is None
        or consensus.verdict is None
        or mode not in {"unknown", *(mode.id for mode in dataset.failure_modes)}
    ):
        return None, "Review consensus does not identify a supported failure-mode ID"
    category = next(iter(incident_categories))
    identity = f"{machine}:{mode}:{category}"
    return (
        EvalCase(
            id="FB-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
            input=candidate.input,
            expected={"machine_id": machine, "failure_mode": mode},
            truth=EvalTruth(category=category),
            cohort="feedback",
            provenance=FeedbackProvenance(
                cluster_key=cluster.id if cluster else None,
                episode_id=candidate.episode_id,
                review_ids=tuple(sorted(candidate.source_review_ids)),
                supporting_review_ids=tuple(consensus.supporting_review_ids),
                source="synthetic",
                failure_mode_basis="reviewer_consensus",
                category_basis="replay_matched_synthetic_scenario",
                analysis_category=cluster.category if cluster else None,
                condition=cluster.condition if cluster else None,
                verdict=consensus.verdict,
                tool_fingerprints=tuple(fingerprints),
            ),
        ),
        None,
    )


def propose_cases(report: Report, existing: Sequence[EvalCase]) -> CaseProposal:
    """Apply admission rules without consulting a planted answer key or seed cause."""
    if report.source != "synthetic":
        raise ValueError("This promotion path requires an explicitly synthetic v2 report")
    if (
        len(set(report.episode_ids)) != report.episode_count
        or len(report.episode_ids) != report.episode_count
    ):
        raise ValueError("Inconsistent report episode membership")
    weights = _weights(report)
    dataset = load_seed()
    categories = _incident_categories(dataset)
    known = {case_identity(case): case for case in existing}
    proposed: dict[str, EvalCase] = {}
    decisions: list[CaseDecision] = []
    cluster_candidates = [
        candidate for cluster in report.clusters for candidate in cluster.eval_cases
    ]
    candidates = report.review_candidates or cluster_candidates
    episode_counts = Counter(candidate.episode_id for candidate in candidates)
    cluster_counts = Counter(cluster.id for cluster in report.clusters)
    memberships: dict[str, list[Cluster]] = defaultdict(list)
    conflicting: set[str] = set()
    by_episode = {candidate.episode_id: candidate for candidate in candidates}
    for item in report.unclassified:
        candidate = by_episode.get(item.episode.id)
        if candidate is not None and (
            candidate.input != item.episode.input
            or candidate.tool_calls
            != [call.model_dump(mode="json") for call in item.episode.tool_calls]
            or candidate.capture_truncated != item.episode.truncated
            or candidate.capture_status != item.episode.status
            or candidate.capture_created_at != item.episode.created_at
            or candidate.capture_completed_at != item.episode.completed_at
            or candidate.review_summary != item.review
            or candidate.review_notes != item.review.notes
            or candidate.expected_failure_mode != item.expected_failure_mode
            or candidate.expected_mode_basis != item.expected_mode_basis
        ):
            conflicting.add(candidate.episode_id)
    for cluster in report.clusters:
        conflicting.update(
            set(cluster.episode_ids) - {candidate.episode_id for candidate in cluster.eval_cases}
        )
        for candidate in cluster.eval_cases:
            memberships[candidate.episode_id].append(cluster)
            source = by_episode.get(candidate.episode_id)
            if (
                (
                    candidate.expected_category is not None
                    and candidate.expected_category != cluster.category
                )
                or source is None
                or source.model_dump(exclude={"expected_category"})
                != (candidate.model_dump(exclude={"expected_category"}))
            ):
                conflicting.add(candidate.episode_id)
    review_records: dict[str, set[str]] = defaultdict(set)
    for candidate in (*candidates, *cluster_candidates):
        for review in candidate.source_reviews:
            review_records[review.id].add(review.model_dump_json())
    groups = [
        (
            memberships[candidate.episode_id][0] if memberships[candidate.episode_id] else None,
            [candidate],
        )
        for candidate in sorted(candidates, key=lambda value: value.episode_id)
    ]
    for cluster, members in groups:
        for candidate in members:
            decision = CaseDecision(
                cluster_key=cluster.id if cluster else None,
                episode_id=candidate.episode_id,
                review_ids=sorted(candidate.source_review_ids),
                status="rejected",
                reason="Inconsistent cluster or source membership",
                case_id=None,
                consensus=None,
                k4=False,
            )
            label = report.labels.get(candidate.episode_id)
            if (
                candidate.episode_id in conflicting
                or len(memberships[candidate.episode_id]) > 1
                or candidate.episode_id not in report.episode_ids
                or episode_counts[candidate.episode_id] != 1
                or any(len(review_records[row.id]) != 1 for row in candidate.source_reviews)
                or (
                    cluster is not None
                    and (
                        cluster.id != cluster_key(cluster.category, cluster.condition)
                        or cluster_counts[cluster.id] != 1
                        or (
                            candidate.expected_category is not None
                            and candidate.expected_category != cluster.category
                        )
                        or candidate.episode_id not in cluster.episode_ids
                        or set(cluster.episode_ids)
                        != {item.episode_id for item in cluster.eval_cases}
                        or len(set(cluster.episode_ids)) != cluster.frequency
                        or label is None
                        or (label.category, label.condition)
                        != (cluster.category, cluster.condition)
                    )
                )
            ):
                decisions.append(decision)
                continue
            calls, fingerprints, capture_error = _capture(candidate)
            if capture_error is not None:
                decisions.append(decision.model_copy(update={"reason": capture_error, "k4": True}))
                continue
            consensus = review_consensus(
                candidate.source_reviews,
                episode_id=candidate.episode_id,
                source_review_ids=candidate.source_review_ids,
                reviewer_weights=weights,
            )
            decision = decision.model_copy(update={"consensus": consensus})
            if consensus.status == "reject" and consensus.reason.startswith("Inconsistent"):
                decisions.append(decision.model_copy(update={"reason": consensus.reason}))
                continue
            if not _matches_summary(candidate, consensus):
                decisions.append(
                    decision.model_copy(update={"reason": "Forged or inconsistent ReviewSummary"})
                )
                continue
            if consensus.status != "admit":
                status = "rejected" if consensus.status == "reject" else consensus.status
                decisions.append(
                    decision.model_copy(update={"status": status, "reason": consensus.reason})
                )
                continue
            if any(
                reviewer_identity(row) != "(anonymous)"
                and (
                    row.feedback.verdict != consensus.verdict
                    or (
                        row.feedback.actual_root_cause
                        and row.feedback.actual_root_cause.strip()
                        and row.feedback.actual_root_cause.strip() != consensus.failure_mode
                    )
                )
                for row in candidate.source_reviews
            ):
                decisions.append(
                    decision.model_copy(
                        update={
                            "status": "expert",
                            "reason": "Explicit reviewer disagreement requires expert resolution",
                        }
                    )
                )
                continue
            case, reason = _candidate_case(
                candidate, cluster, consensus, categories, dataset, calls, fingerprints
            )
            if case is None:
                decisions.append(
                    decision.model_copy(
                        update={
                            "reason": reason,
                            "status": "expert",
                        }
                    )
                )
                continue
            previous = known.get(case_identity(case))
            retained = previous is not None and previous == case.model_copy(
                update={"split": previous.split}
            )
            if previous is not None and not retained:
                decisions.append(
                    decision.model_copy(
                        update={
                            "status": "duplicate",
                            "reason": "Existing machine, failure mode and incident category",
                            "case_id": previous.id,
                        }
                    )
                )
                continue
            proposed[case.id] = case
            known[case_identity(case)] = case
            decisions.append(
                decision.model_copy(
                    update={
                        "status": "admitted",
                        "reason": "Review-supported, replayable feedback case",
                        "case_id": case.id,
                    }
                )
            )
    assigned = assign_splits((*existing, *sorted(proposed.values(), key=lambda case: case.id)))
    assigned_by_id = {case.id: case for case in assigned}
    return CaseProposal(
        report_sha256=report_digest(report),
        cases=[assigned_by_id[case_id] for case_id in sorted(proposed)],
        decisions=decisions,
        limitations=[
            "Feedback is an informational cohort, not part of the quality gate.",
            "Reviews supply verdict and cause; the replayed machine scenario supplies category.",
            "No decisive refs, alternatives, ruled-out modes, checks or canaries are inferred.",
            "Evidence-dependent truth metrics are not applicable without reviewed truth fields.",
            "Report consistency is checked; reviewer assertions are not independently verified.",
            "Cluster membership is optional provenance, never an admission requirement.",
            "Real feedback needs independently supported categories; this path is synthetic-only.",
        ],
    )
