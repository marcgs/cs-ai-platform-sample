import json
from typing import TYPE_CHECKING

import pytest

from cs_platform.eval_reporting import RunMetadata
from cs_platform.eval_runs import RunWriter, load_run, rebuild_report, validate_run_destinations
from cs_platform.evals import CaseResult, EvalCase, EvalSuite, RunOutput, Thresholds

if TYPE_CHECKING:
    from pathlib import Path


def writer(path: Path) -> RunWriter:
    return RunWriter(
        EvalSuite(
            "synthetic",
            (EvalCase(id="../../case", input="<script>injection</script>", expected={}),),
            Thresholds(minimums={"exact": 1}),
            (),
        ),
        path,
        RunMetadata(agent_revision="a", harness_revision="h", model="scripted", target="local"),
        concurrency=1,
    )


def complete(run: RunWriter) -> None:
    case = run.manifest.cases[0]
    run.start(case, 1)
    run.start_attempt(case, 1, 1)
    output = RunOutput(text="<script>answer</script>", episode_id="unavailable")
    run.attempt(case, 1, output)
    run.completed(CaseResult(case_id=case.id, scores={"exact": 1}, output=output))
    run.finish()


def test_torn_final_event_remains_incomplete_without_reconstructing_an_episode(
    tmp_path: Path,
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    events = run.directory / "events.jsonl"
    with events.open("ab") as stream:
        stream.write(b'{"kind":"episode","episode":')
    original = events.read_bytes()
    record = rebuild_report(run.directory)
    assert record.status == "incomplete"
    assert record.failures
    assert record.journal_warning
    assert record.episodes == []
    assert len(record.result.cases) == 1
    assert events.read_bytes() == original
    page = (tmp_path / "results.html").read_text()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "default-src 'none'" in page
    assert len(list(tmp_path.glob("results-transcripts/*.json"))) == 1


@pytest.mark.parametrize("destination", ["results.run", "results.run/episodes.jsonl"])
def test_journal_and_episode_destinations_cannot_overlap(tmp_path: Path, destination: str) -> None:
    with pytest.raises(ValueError, match="overlap"):
        validate_run_destinations(tmp_path / "results.jsonl", episodes_path=tmp_path / destination)
    assert not list(tmp_path.iterdir())


def test_existing_journal_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "results.run").mkdir()
    retained = tmp_path / "results.run" / "manifest.json"
    retained.write_text("retained")
    with pytest.raises(FileExistsError):
        writer(tmp_path / "results.jsonl")
    assert retained.read_text() == "retained"
    assert not (tmp_path / "results.jsonl").exists()


def test_rebuild_refuses_symlink_export_without_touching_target(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    retained = tmp_path / "retained"
    retained.write_text("retained")
    (tmp_path / "results.html").symlink_to(retained)
    with pytest.raises(ValueError, match="symlink"):
        rebuild_report(tmp_path)
    assert retained.read_text() == "retained"
    assert (tmp_path / "results.html").is_symlink()


def test_nonfinal_corruption_is_not_silently_discarded(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    with (run.directory / "events.jsonl").open("a") as stream:
        stream.write("{broken}\n")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_run(tmp_path)


def test_manifest_cannot_redirect_exports_outside_its_directory(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    manifest_path = run.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["result_filename"] = "../retained.jsonl"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="basename"):
        rebuild_report(tmp_path)
    assert not (tmp_path.parent / "retained.jsonl").exists()


def test_legacy_scores_alone_are_not_a_durable_run(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text('{"case_id":"legacy","scores":{"exact":1}}\n')
    with pytest.raises(FileNotFoundError):
        load_run(path)


def test_carriage_return_cannot_hide_committed_corruption(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    with (run.directory / "events.jsonl").open("ab") as stream:
        stream.write(b'{broken}\r{"kind":"finished","status":"complete"}\n')
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_run(tmp_path)


def test_result_cannot_override_the_frozen_regression_gate(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    case = run.manifest.cases[0]
    run.start(case, 1)
    run.completed(CaseResult(case_id=case.id, scores={"exact": 0}, output=RunOutput(), gated=False))
    run.finish()
    with pytest.raises(ValueError, match="frozen regression gate"):
        rebuild_report(tmp_path)
