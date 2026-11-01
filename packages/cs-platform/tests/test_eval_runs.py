import json
import os
import stat
from typing import TYPE_CHECKING

import pytest

from cs_platform import eval_runs
from cs_platform.eval_reporting import RunMetadata
from cs_platform.eval_runs import RunWriter, load_run, rebuild_report, validate_run_destinations
from cs_platform.evals import (
    CaseResult,
    EvalCase,
    EvalPersistenceError,
    EvalSuite,
    RunOutput,
    Thresholds,
)

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


def test_partial_journal_failure_poisoning_preserves_committed_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    journal = run.directory / "events.jsonl"
    original_write = eval_runs._write

    def partial(path: Path, text: str, *, append: bool = False) -> None:
        if path == journal:
            with path.open("ab") as stream:
                stream.write(b'{"kind":')
            raise OSError("partial append")
        original_write(path, text, append=append)

    monkeypatch.setattr(eval_runs, "_write", partial)
    with pytest.raises(EvalPersistenceError):
        run.start(run.manifest.cases[0], 1)
    retained = journal.read_bytes()
    monkeypatch.setattr(eval_runs, "_write", original_write)
    with pytest.raises(EvalPersistenceError, match="previously failed"):
        run.finish(error=OSError("write failed"))
    assert journal.read_bytes() == retained
    record = rebuild_report(tmp_path)
    assert record.status == "incomplete"
    assert len(record.result.cases) == 1
    assert record.journal_warning
    assert journal.read_bytes() == retained


def test_private_artifacts_under_permissive_umask(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        run = writer(tmp_path / "nested" / "results.jsonl")
        complete(run)
        rebuild_report(run.directory)
    finally:
        os.umask(previous)
    for path in (tmp_path / "nested").rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_new_nested_output_directories_sync_their_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[tuple[Path, set[str]]] = []
    sync = eval_runs._sync_directory

    def record(path: Path) -> None:
        observed.append((path, {child.name for child in path.iterdir()}))
        sync(path)

    monkeypatch.setattr(eval_runs, "_sync_directory", record)
    writer(tmp_path / "outer" / "inner" / "results.jsonl")
    assert (tmp_path, {"outer"}) in observed
    assert (tmp_path / "outer", {"inner"}) in observed
    assert (tmp_path / "outer" / "inner", {"results.run"}) in observed
