import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from cs_platform.eval_reporting import RunMetadata, write_artifacts
from cs_platform.evals import (
    CaseResult,
    EvalCase,
    EvalSuite,
    RunOutput,
    SuiteResult,
    Thresholds,
)


def test_artifacts_preserve_transcripts_and_escape_html(tmp_path: Path) -> None:
    dangerous = '</pre><script>alert("bad")</script><img src=x onerror=alert(1)>'
    case = EvalCase(id="../../evil", input=dangerous, expected={})
    suite = EvalSuite(dangerous, (case,), Thresholds(minimums={}), ())
    result = SuiteResult(
        suite=dangerous,
        cases=[
            CaseResult(
                case_id=case.id,
                input=case.input,
                scores={"metric": 1},
                output=RunOutput(text=dangerous),
            )
        ],
    )
    path = tmp_path / "results.jsonl"
    write_artifacts(
        suite,
        result,
        path,
        RunMetadata(
            agent_revision="unchanged-agent",
            harness_revision="new-harness",
            model="scripted",
            target="local",
        ),
    )
    summary = json.loads(path.with_suffix(".summary.json").read_text())
    assert summary["run"]["agent_revision"] == "unchanged-agent"
    assert summary["run"]["harness_revision"] == "new-harness"
    transcript = next((tmp_path / "results-transcripts").glob("*.json"))
    assert json.loads(transcript.read_text())["input"] == dangerous
    page = path.with_suffix(".html").read_text()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "default-src 'none'" in page
