import asyncio
import json
import os
import stat
import sys
from dataclasses import replace
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest
from agent_framework import MCPStreamableHTTPTool, tool
from typer.testing import CliRunner

from cs_platform import eval_runs
from cs_platform.episodes import InMemoryEpisodeStore
from cs_platform.eval_runs import CaseRunKey, load_run
from cs_platform.evals import EvalCase, EvalSuite, RunOutput, Thresholds
from cs_platform.factory import build_agent
from cs_platform.spec import AgentSpec
from cs_platform.testing import ScriptedChatClient, call, text
from csai import app as cli
from csai import eval_cli, foundry, targets
from rca_agent.report import RcaReport

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
ANSWER = RcaReport(machine_id="M-0001", summary="Synthetic", hypotheses=[], missing_information=[])


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.invalid/projects/test")
    monkeypatch.setattr(targets, "configure_telemetry", lambda *_, **__: None)
    count = [0]

    def create(*_: object, **kwargs: Any) -> Any:
        count[0] += 1
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient([[text(ANSWER.model_dump_json())]]),
            store=kwargs["store"],
            response_format=RcaReport,
        )

    suite = EvalSuite(
        "scripted",
        tuple(EvalCase(id=name, input=f"M-0001: {name}", expected={}) for name in "ABC"),
        Thresholds(minimums={"exact": 1}),
        (lambda _case, output: {"exact": float(output.value is not None)},),
    )
    monkeypatch.setitem(
        targets.AGENTS,
        "rca",
        replace(targets.AGENTS["rca"], create=create, load_suite=lambda: suite),
    )
    return count


def invoke(path: Path, *arguments: str) -> Any:
    return runner.invoke(
        cli.app,
        [
            "--no-azd",
            "eval",
            "rca",
            "--concurrency",
            "1",
            "--backoff-s",
            "0",
            "--output",
            str(path),
            *arguments,
        ],
    )


def test_episode_destination_is_reserved_before_any_target_calls(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "episodes.jsonl"
    original = os.open

    def refuse(path, flags, mode=0o777, **kwargs):
        if path == destination:
            raise PermissionError("episode reservation denied")
        return original(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", refuse)
    assert invoke(tmp_path / "results.jsonl", "--episodes-output", str(destination)).exit_code != 0
    assert scripted == [0]


def test_retry_manifest_and_real_loop_use_same_nondefaults(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def create(*_: object, **kwargs: Any) -> Any:
        scripted[0] += 1
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient(
                [] if scripted[0] <= 2 else [[text(ANSWER.model_dump_json())]]
            ),
            store=kwargs["store"],
            response_format=RcaReport,
        )

    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    output = tmp_path / "results.jsonl"
    result = invoke(output, "--retries", "1", "--backoff-s", "0.01")
    assert result.exit_code == 1, result.output
    record = load_run(output)
    manifest = record.manifest
    assert manifest.retries == 1
    assert manifest.backoff_s == 0.01
    assert scripted == [4]
    assert record.result.cases[0].output.attempts == 2


def test_abort_awaits_multiple_active_siblings_and_keeps_repeat_identity(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    active: set[str] = set()
    cleaned: set[str] = set()
    ready = asyncio.Event()
    labels = iter(("A-1", "A-2", "B-1"))

    @tool
    async def interrupt(label: str) -> str:
        """Exercise synthetic concurrent cancellation."""
        active.add(label)
        if len(active) == 3:
            ready.set()
        try:
            if label == "A-1":
                await ready.wait()
                raise asyncio.CancelledError
            await asyncio.Future()
            return "unreachable"
        finally:
            await asyncio.sleep(0)
            cleaned.add(label)

    def create(*_: object, **kwargs: Any) -> Any:
        label = next(labels)
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient([[call("interrupt", label=label)]]),
            store=kwargs["store"],
            tools=[interrupt],
            response_format=RcaReport,
        )

    original = cli.evaluate

    async def bounded(*args: Any, **kwargs: Any) -> Any:
        return await asyncio.wait_for(original(*args, **kwargs), timeout=5)

    monkeypatch.setattr(cli, "evaluate", bounded)
    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    result = invoke(tmp_path / "results.jsonl", "--concurrency", "3", "--repeats", "2")
    assert result.exit_code == 1, result.output
    assert active == cleaned == {"A-1", "A-2", "B-1"}
    record = load_run(tmp_path)
    assert record.status == "incomplete"
    assert {(key.case_id, key.repeat) for key in record.interrupted} == {
        ("A", 1),
        ("A", 2),
        ("B", 1),
    }
    assert {(key.case_id, key.repeat) for key in record.never_started} == {
        ("B", 2),
        ("C", 1),
        ("C", 2),
    }
    captures = [event for event in record.events if isinstance(event, eval_runs.EpisodeCaptured)]
    assert {
        (event.key.case_id, event.key.repeat, event.attempt) for event in captures if event.key
    } == {
        ("A", 1, 1),
        ("A", 2, 1),
        ("B", 1, 1),
    }
    assert len(record.attempts) == len(record.episodes) == 3
    assert all(episode.status == "failed" for episode in record.episodes)


@pytest.mark.parametrize("suffix", [".summary.json", ".html"])
def test_initial_report_reservation_collision_never_calls_target(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, suffix: str
) -> None:
    output = tmp_path / "results.jsonl"
    destination = tmp_path / f"results{suffix}"
    original = eval_runs._write

    def race(path: Path, text: str, *, append: bool = False) -> None:
        if path == destination and text == "":
            path.write_text("another process")
        original(path, text, append=append)

    monkeypatch.setattr(eval_runs, "_write", race)
    result = invoke(output)
    assert result.exit_code != 0
    assert scripted == [0]
    assert destination.read_text() == "another process"


@pytest.mark.parametrize("new_parent", [False, True])
def test_requested_episode_export_is_private_and_synced_before_completion(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, new_parent: bool
) -> None:
    output = tmp_path / "results.jsonl"
    parent = tmp_path / "new" / "nested" if new_parent else tmp_path
    destination = parent / "episodes.jsonl"
    synced: list[tuple[int, int]] = []
    original_sync = os.fsync
    original_finalize = eval_runs.RunWriter.finalize

    def sync(descriptor: int) -> None:
        info = os.fstat(descriptor)
        synced.append((info.st_dev, info.st_ino))
        original_sync(descriptor)

    def finalize(self: eval_runs.RunWriter) -> Any:
        for path in (destination, parent):
            info = path.stat()
            assert (info.st_dev, info.st_ino) in synced
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
        if new_parent:
            assert stat.S_IMODE(parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(parent.parent.stat().st_mode) == 0o700
        return original_finalize(self)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(eval_runs.RunWriter, "finalize", finalize)
    previous = os.umask(0o022)
    try:
        result = invoke(output, "--episodes-output", str(destination))
    finally:
        os.umask(previous)
    assert result.exit_code == 0, result.output
    assert scripted == [3]
    exported = [json.loads(line) for line in destination.read_text().splitlines()]
    assert len(exported) == 3
    assert exported == [episode.model_dump(mode="json") for episode in load_run(output).episodes]


def test_requested_episode_export_fsync_failure_prevents_completion(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "results.jsonl"
    destination = tmp_path / "episodes.jsonl"
    original = os.fsync

    def fail(descriptor: int) -> None:
        if destination.exists() and os.fstat(descriptor).st_ino == destination.stat().st_ino:
            raise OSError("requested episode export fsync failed")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail)
    result = invoke(output, "--episodes-output", str(destination))
    assert result.exit_code == 1
    assert scripted == [0]
    assert not (eval_runs.run_directory(output) / "manifest.json").exists()
    assert not (eval_runs.run_directory(output) / "completion.json").exists()


def test_hard_stop_during_required_export_has_no_complete_marker(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "results.jsonl"
    statuses: list[str] = []
    original_replace = eval_runs._replace
    original_finish = eval_runs.RunWriter.finish

    def interrupt(path: Path, text: str) -> None:
        if path.suffix == ".html":
            statuses.append(load_run(output).status)
            raise KeyboardInterrupt
        original_replace(path, text)

    def no_shutdown_marker(
        self: eval_runs.RunWriter, *, error: BaseException | None = None
    ) -> None:
        if error is None:
            original_finish(self)

    with monkeypatch.context() as patch:
        patch.setattr(eval_runs, "_replace", interrupt)
        patch.setattr(eval_runs.RunWriter, "finish", no_shutdown_marker)
        result = invoke(output)
    assert result.exit_code == 130
    assert statuses
    assert set(statuses) == {"incomplete"}
    record = load_run(output)
    assert record.status == "incomplete"
    assert len(record.result.cases) == 3
    result = runner.invoke(cli.app, ["--no-azd", "eval", "report", str(output)])
    assert result.exit_code == 1
    assert scripted == [3]


def test_episode_export_failure_aborts_without_retrying_successful_model_call(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_write = eval_runs._write
    failed = False

    def fail_once(path: Path, text: str, *, append: bool = False) -> None:
        nonlocal failed
        if path.name == "episodes.jsonl" and text and not failed:
            failed = True
            raise OSError("episode export failed")
        original_write(path, text, append=append)

    monkeypatch.setattr(eval_runs, "_write", fail_once)
    result = invoke(tmp_path / "results.jsonl")
    assert result.exit_code == 1
    assert scripted == [1]
    record = load_run(tmp_path)
    assert record.status == "incomplete"
    assert len(record.episodes) == 1
    assert record.episodes[0].status == "succeeded"
    assert record.result.cases == []


@pytest.mark.parametrize("repeats", [1, 2])
def test_public_cli_cancellation_between_cases_is_durable(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repeats: int
) -> None:
    output = tmp_path / "results.jsonl"

    def interrupt(_: object) -> str:
        retained = load_run(tmp_path)
        assert [case.case_id for case in retained.result.cases] == ["A"]
        assert len(retained.episodes) == 1
        assert len(list(tmp_path.glob("results-transcripts/*.json"))) == 1
        raise asyncio.CancelledError

    monkeypatch.setattr(cli, "describe", interrupt)
    result = invoke(output, "--repeats", str(repeats))
    assert result.exit_code == 1, result.output
    assert scripted == [1]
    record = load_run(tmp_path)
    assert record.status == "incomplete"
    assert record.never_started == [
        CaseRunKey(case_id=case, repeat=repeat)
        for case in "ABC"
        for repeat in range(1, repeats + 1)
        if (case, repeat) != ("A", 1)
    ]
    assert record.interrupted == []
    assert record.result.gate_metrics == {"exact": 1}
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["status"] == "incomplete"
    assert summary["failures"]
    assert "incomplete" in output.with_suffix(".html").read_text()


def test_public_cli_cancellation_in_tool_keeps_actual_failed_episode(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    count = 0

    @tool
    async def interrupted_tool() -> str:
        """A synthetic tool interrupted before returning."""
        raise asyncio.CancelledError

    def create(*_: object, **kwargs: Any) -> Any:
        nonlocal count
        count += 1
        turns = [[call("interrupted_tool")]] if count == 2 else [[text(ANSWER.model_dump_json())]]
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient(turns),
            store=kwargs["store"],
            response_format=RcaReport,
            tools=[interrupted_tool],
        )

    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    result = invoke(tmp_path / "results.jsonl")
    assert result.exit_code == 1, result.output
    record = load_run(tmp_path)
    assert record.status == "incomplete"
    assert [case.case_id for case in record.result.cases] == ["A"]
    assert record.never_started == [CaseRunKey(case_id="C", repeat=1)]
    assert record.interrupted == [CaseRunKey(case_id="B", repeat=1)]
    assert len(record.attempts) == 2
    failure = record.attempts[-1].output.failure
    assert failure is not None
    assert failure.code == "interrupted"
    succeeded, cancelled = record.episodes
    assert succeeded.status == "succeeded"
    assert cancelled.status == "failed"
    assert cancelled.error == "CancelledError: "
    assert cancelled.tool_calls[0].name == "interrupted_tool"
    assert cancelled.tool_calls[0].error == "CancelledError: "


def test_public_cli_export_interruption_keeps_all_results_and_report_can_rebuild(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "results.jsonl"

    def interrupt(*_: object) -> None:
        record = load_run(tmp_path)
        assert len(record.result.cases) == len(record.episodes) == 3
        raise KeyboardInterrupt

    monkeypatch.setattr(eval_runs.ReservedArtifact, "write", interrupt)
    result = invoke(output, "--episodes-output", str(tmp_path / "external.jsonl"))
    assert result.exit_code == 1, result.output
    before = load_run(tmp_path)
    assert before.status == "incomplete"
    assert before.never_started == before.interrupted == []
    journal = tmp_path / "results.run" / "events.jsonl"
    original = journal.read_bytes()
    for path in [
        output,
        output.with_suffix(".summary.json"),
        output.with_suffix(".html"),
        *tmp_path.glob("results-transcripts/*.json"),
        tmp_path / "results.run" / "episodes.jsonl",
    ]:
        path.unlink()
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT")
    monkeypatch.setattr(cli, "make_target", lambda *_, **__: pytest.fail("must stay offline"))
    rebuilt = runner.invoke(cli.app, ["--no-azd", "eval", "report", str(tmp_path)])
    assert rebuilt.exit_code == 1, rebuilt.output
    assert "incomplete" in rebuilt.output
    assert journal.read_bytes() == original
    assert load_run(tmp_path) == before
    assert len(list(tmp_path.glob("results-transcripts/*.json"))) == 3
    assert len(output.read_text().splitlines()) == 3


def test_failed_retry_attempts_are_retained_without_changing_gate(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    creates = 0

    def create(*_: object, **kwargs: Any) -> Any:
        nonlocal creates
        creates += 1
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient([] if creates == 1 else [[text(ANSWER.model_dump_json())]]),
            store=kwargs["store"],
            response_format=RcaReport,
        )

    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    result = invoke(tmp_path / "results.jsonl", "--case", "A")
    assert result.exit_code == 0, result.output
    record = load_run(tmp_path)
    assert record.status == "complete"
    assert record.failures == []
    assert [attempt.output.attempts for attempt in record.attempts] == [1, 2]
    assert record.attempts[0].output.error
    assert [episode.status for episode in record.episodes] == ["failed", "succeeded"]
    assert record.result.cases[0].output.attempts == 2


def test_public_cli_interruption_during_html_export_cannot_pass(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    replace_artifact = eval_runs._replace
    interrupted = False

    def interrupt(path: Path, rendered: str) -> None:
        nonlocal interrupted
        if path.suffix == ".html" and not interrupted:
            interrupted = True
            raise asyncio.CancelledError
        replace_artifact(path, rendered)

    monkeypatch.setattr(eval_runs, "_replace", interrupt)
    result = invoke(tmp_path / "results.jsonl")
    assert result.exit_code == 1, result.output
    assert scripted == [3]
    record = load_run(tmp_path)
    assert record.status == "incomplete"
    assert record.never_started == record.interrupted == []
    assert len(record.result.cases) == len(record.episodes) == 3
    summary = json.loads((tmp_path / "results.summary.json").read_text())
    assert summary["status"] == "incomplete"
    assert summary["failures"]


def test_fatal_evaluator_error_keeps_attempt_and_lists_unstarted_runs(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite = targets.AGENTS["rca"].load_suite()

    def fail(case: EvalCase, _: RunOutput) -> dict[str, float]:
        if case.id == "B":
            raise RuntimeError("offline scoring failed")
        return {"exact": 1}

    monkeypatch.setitem(
        targets.AGENTS,
        "rca",
        replace(targets.AGENTS["rca"], load_suite=lambda: replace(suite, evaluators=(fail,))),
    )
    result = invoke(tmp_path / "results.jsonl")
    assert result.exit_code == 1, result.output
    assert scripted == [2]
    record = load_run(tmp_path)
    assert [case.case_id for case in record.result.cases] == ["A"]
    assert record.interrupted == [CaseRunKey(case_id="B", repeat=1)]
    assert record.never_started == [CaseRunKey(case_id="C", repeat=1)]
    assert len(record.attempts) == len(record.episodes) == 2


def test_default_agent_path_and_complete_report_use_frozen_gates(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "results.jsonl"
    result = runner.invoke(cli.app, ["--no-azd", "eval", "--case", "A", "--output", str(output)])
    assert result.exit_code == 0, result.output
    before = load_run(tmp_path)
    assert before.manifest.metadata.source == "synthetic"
    assert before.manifest.metadata.dataset_version
    assert before.manifest.cases[0].expected == {}
    monkeypatch.setitem(
        targets.AGENTS,
        "rca",
        replace(targets.AGENTS["rca"], load_suite=lambda: pytest.fail("must use frozen suite")),
    )
    monkeypatch.setattr(
        cli, "load_environment", lambda **_: pytest.fail("report must not load azd settings")
    )
    monkeypatch.setattr(
        eval_cli, "load_environment", lambda **_: pytest.fail("report must stay offline")
    )
    result = runner.invoke(cli.app, ["eval", "report", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Gate passed." in result.output
    assert load_run(tmp_path) == before


@pytest.mark.parametrize("quality", [0.0, 1.0])
@pytest.mark.parametrize(
    "error_type", [foundry.FoundryEvalError, RuntimeError, foundry.FoundryEvalPending]
)
def test_optional_publish_failure_never_changes_disk_gate(
    scripted: list[int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    quality: float,
    error_type: type[Exception],
) -> None:
    suite = targets.AGENTS["rca"].load_suite()
    monkeypatch.setitem(
        targets.AGENTS,
        "rca",
        replace(
            targets.AGENTS["rca"],
            load_suite=lambda: replace(
                suite, evaluators=(lambda _case, _output: {"exact": quality},)
            ),
        ),
    )
    adapter = ModuleType("csai.eval_publish")

    def publish(path: Path) -> str:
        assert load_run(path).status == "complete"
        if error_type is foundry.FoundryEvalPending:
            raise foundry.FoundryEvalPending("run-id", "https://example.test/report", "queued")
        raise error_type("offline publishing failure")

    monkeypatch.setattr(adapter, "publish_record", publish, raising=False)
    monkeypatch.setitem(sys.modules, adapter.__name__, adapter)
    result = invoke(tmp_path / "results.jsonl", "--publish")
    assert result.exit_code == (0 if quality == 1 else 1), result.output
    if error_type is foundry.FoundryEvalPending:
        assert "still running" in result.output
        assert "Run ID: run-id" in result.output
        assert "warning:" not in result.output.split("Publishing the durable run to Foundry...")[1]
    else:
        assert "warning:" in result.output
        assert "offline publishing failure" in result.output
    assert load_run(tmp_path).status == "complete"


@pytest.mark.parametrize("failed", [False, True])
def test_standalone_publish_dispatches_only_to_disk_adapter(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failed: bool
) -> None:
    assert invoke(tmp_path / "results.jsonl").exit_code == 0
    adapter = ModuleType("csai.eval_publish")

    def publish(path: Path) -> str:
        assert path == tmp_path
        assert load_run(path).status == "complete"
        if failed:
            raise ValueError("invalid publication")
        return "https://example.invalid/evaluation"

    monkeypatch.setattr(adapter, "publish_record", publish, raising=False)
    monkeypatch.setitem(sys.modules, adapter.__name__, adapter)
    monkeypatch.setattr(cli, "make_target", lambda *_, **__: pytest.fail("must not run"))
    result = runner.invoke(cli.app, ["--no-azd", "eval", "publish", str(tmp_path)])
    assert result.exit_code == (2 if failed else 0), result.output
    assert ("invalid publication" if failed else "Foundry report:") in result.output


@pytest.mark.parametrize("failed", [False, True])
def test_actual_tool_definitions_are_pinned_in_successful_and_failed_case_records(
    scripted: list[int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failed: bool
) -> None:
    @tool(name="diagnostics___machine_status")
    def machine_status(machine_id: str) -> str:
        """Return synthetic machine status."""
        return f"{machine_id}: stable"

    def create(*_: object, **kwargs: Any) -> Any:
        turns = [[call("diagnostics___machine_status", machine_id="M-0001")]]
        if not failed:
            turns.append([text(ANSWER.model_dump_json())])
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient(turns),
            store=kwargs["store"],
            tools=[machine_status],
            response_format=RcaReport,
        )

    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    result = invoke(tmp_path / "results.jsonl", "--case", "A", "--retries", "0")
    assert result.exit_code == (1 if failed else 0), result.output
    before = load_run(tmp_path)
    output = before.result.cases[0].output
    assert output.tool_calls == ["diagnostics___machine_status"]
    assert output.tool_definitions == [machine_status.to_json_schema_spec()]
    assert before.attempts[0].output.tool_definitions == output.tool_definitions
    machine_status.description = "Changed after capture; must not appear in retained schema."
    rebuilt = runner.invoke(cli.app, ["eval", "report", str(tmp_path)])
    assert rebuilt.exit_code == result.exit_code, rebuilt.output
    assert load_run(tmp_path) == before


def test_discovered_mcp_schemas_use_actual_prefixed_functions_not_wrapper_definitions() -> None:
    @tool(name="diagnostics___discovered")
    def discovered(machine_id: str) -> str:
        """A discovered synthetic MCP function."""
        return machine_id

    mcp = MCPStreamableHTTPTool("diagnostics", "https://example.invalid/mcp")
    mcp.functions.append(discovered)
    agent = build_agent(
        AgentSpec(name="test", version="1", description="test", instructions="test"),
        client=ScriptedChatClient([]),
        store=InMemoryEpisodeStore(),
    )
    agent.mcp_tools.append(mcp)
    assert targets.snapshot_tool_definitions(agent) == [discovered.to_json_schema_spec()]
