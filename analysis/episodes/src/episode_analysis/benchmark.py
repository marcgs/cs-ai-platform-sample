"""Separate, model-free benchmark: this is the ONLY consumer of answer keys."""

import hashlib
from typing import TYPE_CHECKING

from episode_analysis.models import Record

if TYPE_CHECKING:
    from diagnostics_domain.feedback_models import AnswerKey
    from episode_analysis.models import Report


class PatternRecovery(Record):
    pattern_id: str
    expected_count: int
    matched_count: int
    best_cluster_rank: int | None
    cluster_precision: float | None
    pattern_recall: float
    routed_correctly: bool
    cluster_count: int


class Benchmark(Record):
    classifier: str
    sample_size: int
    classified_count: int
    category_accuracy: float | None
    route_accuracy: float | None
    clusters_per_pattern: float | None
    end_to_end_category_recall: float | None
    control_count: int
    control_false_positives: int
    recovery: list[PatternRecovery]
    limitations: list[str]


def evaluate(
    report: Report, key: AnswerKey, *, sample_size: int = 100, allow_subset: bool = False
) -> Benchmark:
    """Measure recovery and a deterministic sample without influencing analysis.

    Call on a separately generated seed not used to develop the classifier. There is
    no tuned pass threshold: denominators, coverage and per-pattern purity are exposed.
    """
    if report.source != "synthetic" or sample_size < 1:
        raise ValueError("Benchmark requires a synthetic report and a positive sample size")
    truths = {row.episode_id: row for row in key.episodes}
    population = set(report.episode_ids)
    if (
        not population
        or population - truths.keys()
        or (not allow_subset and population != truths.keys())
        or set(report.labels) - population
    ):
        raise ValueError("Report and answer key refer to different populations")
    categories = {
        episode_id: pattern.classification
        for pattern in key.patterns
        for episode_id in pattern.episode_ids
        if episode_id in population
    }
    sample = sorted(categories, key=lambda value: hashlib.sha256(value.encode()).hexdigest())[
        :sample_size
    ]
    classified = [episode_id for episode_id in sample if episode_id in report.labels]
    correct = sum(
        report.labels[episode_id].category == categories[episode_id] for episode_id in classified
    )
    controls = {
        row.episode_id
        for row in key.episodes
        if row.pattern_id is None and row.episode_id in population
    }
    recovery: list[PatternRecovery] = []
    routes = {"learner": "learner_brief", "knowledge": "knowledge_proposal", "backlog": "backlog"}
    expected_routes = {
        episode_id: routes[pattern.route]
        for pattern in key.patterns
        for episode_id in pattern.episode_ids
    }
    observed_routes = {
        episode_id: cluster.route
        for cluster in report.clusters
        for episode_id in cluster.episode_ids
    }
    for pattern in key.patterns:
        expected = set(pattern.episode_ids).intersection(population)
        candidates = [
            (rank, cluster, len(expected.intersection(cluster.episode_ids)))
            for rank, cluster in enumerate(report.clusters, start=1)
            if cluster.category == pattern.classification
        ]
        best = max(candidates, key=lambda entry: (entry[2], -entry[0]), default=None)
        rank, cluster, count = best if best else (None, None, 0)
        recovery.append(
            PatternRecovery(
                pattern_id=pattern.id,
                expected_count=len(expected),
                matched_count=count,
                best_cluster_rank=rank if count else None,
                cluster_precision=count / cluster.frequency if cluster and count else None,
                pattern_recall=count / len(expected) if expected else 0,
                routed_correctly=bool(cluster and count and cluster.route == routes[pattern.route]),
                cluster_count=sum(
                    bool(expected.intersection(cluster.episode_ids)) for cluster in report.clusters
                ),
            )
        )
    return Benchmark(
        classifier=report.classifier,
        sample_size=len(sample),
        classified_count=len(classified),
        category_accuracy=correct / len(classified) if classified else None,
        route_accuracy=(
            sum(
                observed_routes.get(episode_id) == expected_routes[episode_id]
                for episode_id in classified
            )
            / len(classified)
            if classified
            else None
        ),
        clusters_per_pattern=(
            sum(row.cluster_count for row in recovery if row.expected_count)
            / sum(bool(row.expected_count) for row in recovery)
            if any(row.expected_count for row in recovery)
            else None
        ),
        end_to_end_category_recall=correct / len(sample) if sample else None,
        control_count=len(controls),
        control_false_positives=len(controls.intersection(report.labels)),
        recovery=recovery,
        limitations=[
            "The sample must come from an independently held-out generation seed.",
            "Injected test labels do not validate Foundry model accuracy.",
            "Category accuracy excludes unclassified cases; end-to-end recall includes them.",
            "Cluster recall/precision expose splitting and contamination; no tuned threshold.",
            "Recovery denominators refer only to report episodes, not unsampled population.",
            "Fragment counts include wrong-category clusters; empty patterns are excluded "
            "from the clusters-per-pattern mean.",
            "Route accuracy uses classified sample members, not just each pattern's best cluster.",
        ],
    )
