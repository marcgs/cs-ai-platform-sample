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


def write_artifacts(
    suite: EvalSuite,
    result: SuiteResult,
    path: Path,
    metadata: RunMetadata,
) -> None:
    """Write JSONL, run metadata, complete per-case transcripts and a static HTML report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    transcript_dir = path.parent / f"{path.stem}-transcripts"
    transcript_dir.mkdir(exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(result.to_jsonl())
    summary = {
        "run": metadata.model_dump(mode="json"),
        "suite": result.suite,
        "case_count": len({case.case_id for case in result.cases}),
        "case_runs": len(result.cases),
        "quality_case_runs": len(result.quality_cases),
        "gate_case_ids": sorted({case.case_id for case in result.cases if case.gated}),
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
    summary_path = path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
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
        (transcript_dir / filename).write_text(rendered + "\n", encoding="utf-8")
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
    path.with_suffix(".html").write_text(page, encoding="utf-8")
