"""Pure preparation and async analysis, also callable from a notebook."""

import hashlib
import re
from collections import defaultdict
from statistics import mean
from typing import TYPE_CHECKING

from diagnostics_domain.feedback_models import Review
from episode_analysis.enrich import enrich
from episode_analysis.models import (
    Cluster,
    EnrichedEpisode,
    EvalCase,
    Label,
    LabeledEpisode,
    Record,
    Report,
    ReviewerAgreement,
    Route,
)
from episode_analysis.reviews import summarize

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cs_platform.episodes import Episode
    from diagnostics_domain.dataset import DiagnosticsDataset
    from episode_analysis.classifier import CachedClassifier


class Prepared(Record):
    """A source-separated population with only conservatively agreed misses."""

    source: str
    episode_count: int
    episode_ids: list[str]
    reviewed_count: int
    uncertain_count: int
    agreement: dict[str, ReviewerAgreement]
    candidates: list[EnrichedEpisode]


def prepare(
    episodes: Sequence[Episode],
    reviews: Sequence[Review],
    dataset: DiagnosticsDataset | None = None,
) -> Prepared:
    """Validate sources, deduplicate rows and enrich agreed misses without truth."""
    unique: dict[str, Episode] = {}
    for episode in episodes:
        previous = unique.get(episode.id)
        if previous is not None and previous != episode:
            raise ValueError(f"Conflicting duplicate episode: {episode.id}")
        unique[episode.id] = episode
    sources = {episode.source for episode in unique.values()} | {row.source for row in reviews}
    if len(sources) != 1:
        raise ValueError("Provide one nonempty source population; split synthetic and real reports")
    for row in reviews:
        if row.episode_id not in unique:
            raise ValueError(f"Review references unknown episode: {row.episode_id}")
    combined = list(reviews)
    for episode in unique.values():
        if episode.feedback:
            combined.append(
                Review(
                    id=f"embedded-{episode.id}",
                    episode_id=episode.id,
                    source=episode.source,
                    feedback=episode.feedback,
                )
            )
    summaries, agreement = summarize(combined)
    candidates: list[EnrichedEpisode] = []
    uncertain = 0
    for episode in sorted(unique.values(), key=lambda row: row.id):
        summary = summaries.get(episode.id)
        if summary is None or summary.verdict is None:
            uncertain += 1
            continue
        if summary.verdict == "correct":
            continue
        candidates.append(enrich(episode, summary, dataset))
    return Prepared(
        source=next(iter(sources)),
        episode_count=len(unique),
        episode_ids=sorted(unique),
        reviewed_count=len(summaries),
        uncertain_count=uncertain,
        agreement=agreement,
        candidates=candidates,
    )


def _route(category: str) -> Route:
    if category == "knowledge_gap":
        return "knowledge_proposal"
    if category in {"data_quality", "tool_error"}:
        return "backlog"
    return "learner_brief"


def _handoff(category: str) -> str:
    if category == "knowledge_gap":
        return (
            "Propose a catalog or code-mapping correction using the representative evidence. "
            "Require domain review and replay before changing knowledge."
        )
    if category in {"data_quality", "tool_error"}:
        return (
            "Investigate the captured tool/data anomaly. File a backlog finding with the "
            "representative calls, machine conditions and reproducing eval cases."
        )
    return (
        "Prepare an iteration-4 learner brief for the observed evidence-handling failure. "
        "Use the representative transcripts and reproducing cases; independently confirm "
        "reviewer claims before proposing a procedure change. Do not edit the agent automatically."
    )


def _clusters(rows: Sequence[LabeledEpisode]) -> list[Cluster]:
    groups: dict[tuple[str, str], list[LabeledEpisode]] = defaultdict(list)
    for row in rows:
        condition = re.sub(r"[^a-z0-9]+", "_", row.label.condition.casefold()).strip("_")
        groups[(row.label.category, condition or "unspecified")].append(row)
    clusters: list[Cluster] = []
    for (category, condition), members in sorted(groups.items()):
        members.sort(key=lambda row: (-row.input.downtime_hours, row.input.episode.id))
        inputs = [member.input for member in members]
        impact = mean(item.downtime_hours for item in inputs)
        clusters.append(
            Cluster(
                id=hashlib.sha256(f"{category}:{condition}".encode()).hexdigest()[:16],
                category=members[0].label.category,
                condition=condition,
                route=_route(category),
                handoff=_handoff(category),
                evidence_summaries=[member.label.rationale for member in members[:3]],
                frequency=len(inputs),
                mean_downtime_hours=impact,
                score=len(inputs) * impact,
                episode_ids=[item.episode.id for item in inputs],
                representative_episode_ids=[item.episode.id for item in inputs[:3]],
                platforms=sorted({item.platform for item in inputs if item.platform}),
                software_releases=sorted(
                    {item.software_release for item in inputs if item.software_release}
                ),
                expected_failure_modes=sorted(
                    {item.expected_failure_mode for item in inputs if item.expected_failure_mode}
                ),
                eval_cases=[
                    EvalCase(
                        episode_id=item.episode.id,
                        input=item.episode.input,
                        expected_category=members[0].label.category,
                        expected_failure_mode=item.expected_failure_mode,
                        expected_mode_basis=item.expected_mode_basis,
                        tool_calls=[
                            call.model_dump(mode="json") for call in item.episode.tool_calls
                        ],
                        review_notes=item.review.notes,
                    )
                    for item in inputs
                ],
            )
        )
    return sorted(clusters, key=lambda cluster: (-cluster.score, -cluster.frequency, cluster.id))


async def analyze(prepared: Prepared, classifier: CachedClassifier | None = None) -> Report:
    """Label sequentially; failures stay visible and are not converted into labels."""
    rows: list[LabeledEpisode] = []
    labels: dict[str, Label] = {}
    errors: dict[str, str] = {}
    for item in prepared.candidates:
        if classifier is None:
            continue
        try:
            label = await classifier(item)
        except Exception as error:
            # SDK error messages can contain endpoints and transcript content.
            errors[item.episode.id] = type(error).__name__
            continue
        labels[item.episode.id] = label
        rows.append(LabeledEpisode(input=item, label=label))
    return Report(
        source="synthetic" if prepared.source == "synthetic" else "real",
        classifier=classifier.config.model if classifier else "unlabeled-offline",
        episode_count=prepared.episode_count,
        episode_ids=prepared.episode_ids,
        reviewed_count=prepared.reviewed_count,
        uncertain_count=prepared.uncertain_count,
        reviewer_agreement=prepared.agreement,
        clusters=_clusters(rows),
        labels=labels,
        unclassified=[item for item in prepared.candidates if item.episode.id not in labels],
        errors=errors,
        limitations=[
            "Reviewer consensus is not ground truth; uncertain episodes are excluded.",
            "Downtime is a historical proxy, not measured attributable impact.",
            "Labels and reproducing eval cases require expert review before promotion.",
            "Without explicit classification, candidates stay unlabeled; no clusters are inferred.",
        ],
    )
