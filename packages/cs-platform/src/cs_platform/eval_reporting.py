"""Private, offline evaluation artifacts. HTML contains escaped text, never executable data."""

import hashlib
import html
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path

    from cs_platform.evals import EvalSuite, SuiteResult


class RunMetadata(BaseModel):
    """Keep the evaluated agent's revision independent from the measuring harness."""

    model_config = ConfigDict(extra="forbid")

    agent_revision: str
    harness_revision: str
    harness_dirty: bool = False
    model: str
    target: str
    repeats: int = 1
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def artifact_paths(path: Path) -> tuple[Path, Path, Path, Path]:
    """Return results, summary, HTML and transcript destinations."""
    return (
        path,
        path.with_suffix(".summary.json"),
        path.with_suffix(".html"),
        path.parent / f"{path.stem}-transcripts",
    )


def validate_artifact_destinations(path: Path, *, episodes_path: Path | None = None) -> None:
    """Reject existing or overlapping artifact destinations before running an agent."""
    destinations = list(artifact_paths(path))
    if episodes_path is not None:
        destinations.append(episodes_path)
    resolved = [destination.resolve() for destination in destinations]
    for index, destination in enumerate(destinations):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"artifact destination already exists: {destination}")
        if any(
            resolved[index] == other
            or resolved[index] in other.parents
            or other in resolved[index].parents
            for other in resolved[index + 1 :]
        ):
            raise ValueError(f"artifact destinations overlap: {destination}")


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def write_artifacts(
    suite: EvalSuite,
    result: SuiteResult,
    path: Path,
    metadata: RunMetadata,
) -> None:
    """Write JSONL, run metadata, complete per-case transcripts and a static HTML report."""
    validate_artifact_destinations(path)
    _, summary_path, html_path, transcript_dir = artifact_paths(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir()
    _write_new(path, result.to_jsonl())
    summary = {
        "run": metadata.model_dump(mode="json"),
        "suite": result.suite,
        "case_count": len({case.case_id for case in result.cases}),
        "case_runs": len(result.cases),
        "quality_case_runs": len(result.quality_cases),
        "gate_case_ids": sorted({case.case_id for case in result.cases if case.gated}),
        "minimum_score_metrics": sorted(result.minimum_score_metrics),
        "metrics": result.metrics,
        "intervals": result.intervals,
        "gate_metrics": result.gate_metrics,
        "gate_intervals": result.gate_intervals,
        "groups": result.groups,
        "failures": result.failures(suite.thresholds),
        "warnings": result.warnings(suite.thresholds),
        "bootstrap": {
            "method": "hierarchical case then repeat percentile 95%",
            "samples": result.bootstrap_samples,
            "seed": result.bootstrap_seed,
        },
    }
    _write_new(summary_path, json.dumps(summary, indent=2) + "\n")
    cases = {case.id: case for case in suite.cases}
    sections: list[str] = []
    for case in result.cases:
        identity = hashlib.sha256(case.case_id.encode()).hexdigest()[:16]
        filename = f"{identity}-{case.repeat}.json"
        transcript = {
            "case": cases[case.case_id].model_dump(mode="json"),
            **case.model_dump(mode="json"),
        }
        rendered = json.dumps(transcript, indent=2)
        _write_new(transcript_dir / filename, rendered + "\n")
        link = html.escape(f"./{transcript_dir.name}/{filename}", quote=True)
        label = html.escape(f"{case.case_id} repeat {case.repeat}")
        sections.append(
            f'<details><summary><a href="{link}">{label}</a></summary>'
            f"<pre>{html.escape(rendered)}</pre></details>"
        )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; base-uri 'none'; form-action 'none'\">"
        f"<title>{html.escape(suite.name)} evaluation</title><body>"
        f"<h1>{html.escape(suite.name)} evaluation</h1>"
        "<p>Private synthetic evaluation data. Only regression cases determine the gate.</p>"
        f"<pre>{html.escape(json.dumps(summary, indent=2))}</pre>"
        + "".join(sections)
        + "</body></html>\n"
    )
    _write_new(html_path, page)
