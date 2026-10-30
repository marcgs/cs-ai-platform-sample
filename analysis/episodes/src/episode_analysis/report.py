"""JSON and inert Markdown reports; never execute or render transcript instructions."""

import html
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from episode_analysis.models import Report


def _plain(value: str) -> str:
    single_line = " ".join(value.split())
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(single_line))


def markdown(report: Report) -> str:
    """Escape every data-derived value, including model-generated condition strings."""
    lines = [
        "# Episode clusters",
        "",
        f"Source: {_plain(report.source)}. Classifier: {_plain(report.classifier)}.",
        f"Episodes: {report.episode_count}; uncertain: {report.uncertain_count}; "
        f"classification errors: {len(report.errors)}.",
        f"Unlabeled candidates: {len(report.unclassified)}; see enriched inputs in JSON.",
        "",
        "Scores are frequency x historical mean downtime hours, not measured savings.",
        "",
    ]
    for index, cluster in enumerate(report.clusters, start=1):
        lines += [
            f"## {index}. {_plain(cluster.category)}: {_plain(cluster.condition)}",
            "",
            f"Route: {_plain(cluster.route)}. Frequency: {cluster.frequency}. "
            f"Score: {cluster.score:.2f} proxy hours.",
            _plain(cluster.handoff),
            "Observed evidence: "
            + "; ".join(_plain(value) for value in cluster.evidence_summaries),
            "Representative episodes: "
            + ", ".join(_plain(value) for value in cluster.representative_episode_ids),
            "Platforms: " + ", ".join(_plain(value) for value in cluster.platforms),
            "Software releases: " + ", ".join(_plain(value) for value in cluster.software_releases),
            f"Reproducing eval cases in JSON: {len(cluster.eval_cases)}. "
            "Reviewer-derived expected modes need independent confirmation.",
            "",
        ]
    lines += ["## Limitations", ""] + [f"- {_plain(value)}" for value in report.limitations]
    return "\n".join(lines) + "\n"


def write_report(report: Report, prefix: Path) -> None:
    """Write sibling JSON and Markdown files below a user-selected output prefix."""
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    prefix.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
