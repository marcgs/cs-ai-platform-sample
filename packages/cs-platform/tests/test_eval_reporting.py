import json
from typing import TYPE_CHECKING

import pytest

from cs_platform import eval_reporting

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


@pytest.mark.parametrize(
    "destination",
    ["results.jsonl", "results.summary.json", "results.html", "results-transcripts"],
)
def test_existing_artifacts_are_rejected_without_writing(tmp_path: Path, destination: str) -> None:
    retained = tmp_path / destination
    retained.write_text("retained", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_artifacts(
            EvalSuite("demo", (), Thresholds(minimums={}), ()),
            SuiteResult(suite="demo", cases=[]),
            tmp_path / "results.jsonl",
            RunMetadata(agent_revision="a", harness_revision="h", model="scripted", target="local"),
        )
    assert retained.read_text("utf-8") == "retained"
    assert set(tmp_path.iterdir()) == {retained}


def test_aliased_results_and_successive_shared_stems_are_rejected(tmp_path: Path) -> None:
    suite = EvalSuite("demo", (), Thresholds(minimums={}), ())
    result = SuiteResult(suite="demo", cases=[])
    metadata = RunMetadata(
        agent_revision="a", harness_revision="h", model="scripted", target="local"
    )
    with pytest.raises(ValueError, match="overlap"):
        write_artifacts(suite, result, tmp_path / "results.html", metadata)
    assert not list(tmp_path.iterdir())
    write_artifacts(suite, result, tmp_path / "results.jsonl", metadata)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        write_artifacts(suite, result, tmp_path / "results.json", metadata)
    assert not (tmp_path / "results.json").exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("destination", ["results.summary.json", "results.html"])
def test_writers_refuse_files_created_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    validate = eval_reporting.validate_artifact_destinations
    retained = tmp_path / destination

    def race(path: Path) -> None:
        validate(path)
        retained.write_text("another run", encoding="utf-8")

    monkeypatch.setattr(eval_reporting, "validate_artifact_destinations", race)
    with pytest.raises(FileExistsError):
        write_artifacts(
            EvalSuite("demo", (), Thresholds(minimums={}), ()),
            SuiteResult(suite="demo", cases=[]),
            tmp_path / "results.jsonl",
            RunMetadata(agent_revision="a", harness_revision="h", model="scripted", target="local"),
        )
    assert retained.read_text("utf-8") == "another run"
