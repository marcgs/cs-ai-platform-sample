import html
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from cs_platform import eval_runs
from cs_platform.episodes import Episode
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


def writer(path: Path, *, episodes_path: Path | None = None) -> RunWriter:
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
        episodes_path=episodes_path,
    )


def complete(run: RunWriter, *, finish: bool = True) -> None:
    case = run.manifest.cases[0]
    run.start(case, 1)
    run.start_attempt(case, 1, 1)
    output = RunOutput(text="<script>answer</script>", episode_id="unavailable")
    run.attempt(case, 1, output)
    run.completed(CaseResult(case_id=case.id, scores={"exact": 1}, output=output))
    if finish:
        run.finish()


@pytest.mark.parametrize("fail_sync", [False, True])
def test_direct_finalization_writes_and_syncs_requested_episodes_before_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_sync: bool
) -> None:
    destination = tmp_path / "requested" / "episodes.jsonl"
    run = writer(tmp_path / "results.jsonl", episodes_path=destination)
    episode = Episode(agent="test", agent_version="1", input=run.manifest.cases[0].input)
    run.episode(episode)
    complete(run, finish=False)
    synced: set[int] = set()
    inodes = {destination.stat().st_ino, destination.parent.stat().st_ino}
    original = os.fsync

    def sync(descriptor: int) -> None:
        inode = os.fstat(descriptor).st_ino
        if inode in inodes:
            assert not (run.directory / "completion.json").exists()
            assert destination.read_text() == episode.model_dump_json() + "\n"
            if fail_sync:
                raise OSError("requested export sync failed")
            synced.add(inode)
        original(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    if fail_sync:
        with pytest.raises(OSError, match="requested export sync failed"):
            run.finalize()
        assert load_run(run.directory).status == "incomplete"
        assert not (run.directory / "completion.json").exists()
    else:
        record = run.finalize()
        assert record.status == "complete"
        assert record.episodes == [episode]
        assert synced == inodes
        assert destination.read_text() == episode.model_dump_json() + "\n"
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_results_append_kernel_rejects_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = writer(tmp_path / "results.jsonl")
    retained = tmp_path / "retained"
    retained.write_text("untouched")
    original = os.open

    def race(path, flags, mode=0o777, **kwargs):
        if path == run.output and flags & os.O_APPEND:
            path.unlink()
            path.symlink_to(retained)
        return original(path, flags, mode, **kwargs)

    run.start(run.manifest.cases[0], 1)
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", race)
        with pytest.raises(OSError, match="symbolic"):
            run.completed(
                CaseResult(case_id=run.manifest.cases[0].id, scores={}, output=RunOutput())
            )
    run.finish(error=OSError())
    assert retained.read_text() == "untouched"


def test_rebuild_cannot_replace_newer_exports_from_an_active_writer(
    tmp_path: Path,
) -> None:
    run = writer(tmp_path / "results.jsonl")
    case = run.manifest.cases[0]
    run.start(case, 1)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(rebuild_report, run.directory)
        with pytest.raises(OSError, match="active"):
            pending.result(timeout=2)
        run.episode(Episode(agent="test", agent_version="1", input=case.input))
        run.completed(
            CaseResult(case_id=case.id, scores={"exact": 1}, output=RunOutput(text="answer"))
        )
        run.finalize()
    record = load_run(run.directory)
    assert record.status == "complete"
    assert len(run.output.read_text().splitlines()) == len(record.result.cases) == 1
    assert len((run.directory / "episodes.jsonl").read_text().splitlines()) == 1
    assert json.loads((tmp_path / "results.summary.json").read_text())["status"] == "complete"
    assert '"status": "complete"' in html.unescape((tmp_path / "results.html").read_text())
    assert rebuild_report(run.directory) == record


@pytest.mark.parametrize("suffix", [".summary.json", ".html"])
def test_reports_are_reserved_exclusively_before_cases(tmp_path: Path, suffix: str) -> None:
    run = writer(tmp_path / "results.jsonl")
    with pytest.raises(FileExistsError):
        (tmp_path / f"results{suffix}").open("x")
    assert load_run(run.directory).result.cases == []


def test_manifest_publication_interruption_has_a_recoverable_empty_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = eval_runs._write

    def interrupt(path: Path, text: str, *, append: bool = False) -> None:
        original(path, text, append=append)
        if path.name == "manifest.json":
            raise KeyboardInterrupt

    monkeypatch.setattr(eval_runs, "_write", interrupt)
    output = tmp_path / "results.jsonl"
    with pytest.raises(KeyboardInterrupt):
        writer(output)
    record = rebuild_report(output)
    assert record.status == "incomplete"
    assert len(record.never_started) == 1
    assert not record.events


def test_precommit_visible_reports_never_claim_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run, finish=False)

    def interrupt(**_: object) -> None:
        summary = json.loads((tmp_path / "results.summary.json").read_text())
        assert summary["status"] == "incomplete"
        assert summary["failures"]
        assert '"status": "complete"' not in html.unescape((tmp_path / "results.html").read_text())
        raise KeyboardInterrupt

    monkeypatch.setattr(run, "finish", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run.finalize()
    assert load_run(run.directory).status == "incomplete"


@pytest.mark.parametrize("failure", ["file", "directory"])
def test_full_completion_line_with_failed_fsync_cannot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run, finish=False)
    original = os.fsync

    def fail(descriptor: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if is_directory == (failure == "directory"):
            raise OSError("completion fsync failed")
        original(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        with pytest.raises(EvalPersistenceError):
            run.finish()
    events = (run.directory / "events.jsonl").read_bytes()
    assert json.loads(events.splitlines()[-1])["status"] == "complete"
    with pytest.raises(EvalPersistenceError):
        run.finish(error=OSError())
    assert rebuild_report(run.directory).status == "incomplete"
    assert events == (run.directory / "events.jsonl").read_bytes()


def test_failed_certificate_directory_sync_removes_visible_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run, finish=False)
    original = eval_runs._sync_directory

    def fail(path: Path) -> None:
        if (run.directory / "completion.json").exists():
            raise OSError("certificate directory fsync failed")
        original(path)

    with monkeypatch.context() as patch:
        patch.setattr(eval_runs, "_sync_directory", fail)
        with pytest.raises(EvalPersistenceError):
            run.finish()
    assert not (run.directory / "completion.json").exists()
    assert rebuild_report(run.directory).status == "incomplete"


def test_hard_stop_after_complete_line_before_commit_remains_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run, finish=False)
    original = eval_runs._sync_directory

    def interrupt(path: Path) -> None:
        if (
            json.loads((run.directory / "events.jsonl").read_bytes().splitlines()[-1]).get("status")
            == "complete"
        ):
            raise KeyboardInterrupt
        original(path)

    with monkeypatch.context() as patch:
        patch.setattr(eval_runs, "_sync_directory", interrupt)
        with pytest.raises(KeyboardInterrupt):
            run.finalize()
    assert load_run(run.directory).status == "incomplete"
    assert json.loads((tmp_path / "results.summary.json").read_text())["status"] == "incomplete"
    assert '"status": "complete"' not in html.unescape((tmp_path / "results.html").read_text())


def test_legacy_completion_without_certificate_is_still_readable(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    manifest_path = run.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["completion_protocol"]
    manifest_path.write_text(json.dumps(manifest))
    (run.directory / "completion.json").unlink()
    assert load_run(run.directory).status == "complete"


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
    (tmp_path / "results.html").unlink()
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
    run.close()
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


@pytest.mark.parametrize("metadata", ["original", "challenge", "feedback", None])
def test_legacy_cohort_is_recovered_without_rewriting_evidence(
    tmp_path: Path, metadata: str | None
) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    manifest_path = run.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if metadata is None:
        manifest.pop("cohorts")
    else:
        manifest["cohorts"] = {run.manifest.cases[0].id: metadata}
    manifest_path.write_text(json.dumps(manifest))
    journal = (run.directory / "events.jsonl").read_bytes()
    record = rebuild_report(run.directory)
    cohort = metadata or "original"
    case = record.result.cases[0]
    assert case.cohort == cohort
    assert case.scores == {"exact": 1}
    assert case.output.episode_id == "unavailable"
    assert record.episodes == []
    assert record.result.gate_metrics == {"exact": 1}
    assert record.status == "complete"
    summary = json.loads((tmp_path / "results.summary.json").read_text())
    assert summary["groups"]["cohort"] == {cohort: {"exact": 1}}
    assert summary["group_intervals"]["cohort"] == {cohort: {"exact": [1, 1]}}
    assert (run.directory / "events.jsonl").read_bytes() == journal


def test_result_cannot_override_the_frozen_cohort(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    case = run.manifest.cases[0]
    run.start(case, 1)
    run.completed(
        CaseResult(case_id=case.id, scores={"exact": 1}, output=RunOutput(), cohort="feedback")
    )
    run.finish()
    with pytest.raises(ValueError, match="frozen cohort"):
        rebuild_report(run.directory)


def test_frozen_cohort_must_agree_with_explicit_case_metadata(tmp_path: Path) -> None:
    run = writer(tmp_path / "results.jsonl")
    complete(run)
    path = run.directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["cases"][0]["cohort"] = "feedback"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="frozen cohort"):
        load_run(run.directory)


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
