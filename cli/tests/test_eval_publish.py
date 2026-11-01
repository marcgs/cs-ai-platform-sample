"""Publish real durable records through the public CLI with Foundry faked."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cs_platform.episodes import Episode, ToolCall
from cs_platform.eval_reporting import RunMetadata
from cs_platform.eval_runs import RunWriter, read_run
from cs_platform.evals import (
    CaseResult,
    EvalCase,
    EvalSuite,
    EvalTruth,
    RunError,
    RunOutput,
    Thresholds,
)
from cs_platform.settings import PlatformSettings
from csai import eval_publish, foundry
from csai.app import app


@pytest.fixture
def saved_run(tmp_path):
    case = EvalCase(
        id="fixture",
        input="M-0001: synthetic incident",
        expected={"machine_id": "M-0001", "failure_mode_id": "FM-01"},
        truth=EvalTruth(category="clean", decisive_refs=("EV-000001",)),
        split="train",
    )
    suite = EvalSuite("fixture", (case,), Thresholds(minimums={"exact": 1.0}), ())
    writer = RunWriter(
        suite,
        tmp_path / "results.jsonl",
        RunMetadata(
            agent_revision="saved-agent-revision",
            harness_revision="saved-harness-revision",
            agent_version="saved-agent-version",
            skill_version="saved-skill-version",
            dataset_version="saved-dataset-version",
            model="saved-agent-model",
            target="local",
            source="synthetic",
            started_at=datetime.fromisoformat("2026-10-30T12:00:00+00:00"),
        ),
        concurrency=1,
    )
    writer.start(case, 1)
    writer.start_attempt(case, 1, 1)
    call = ToolCall(
        name="diagnostics___get_machine_context",
        arguments={"machine_id": "M-0001"},
        result=json.dumps({"machine_id": "M-0001", "signals": []}),
        started_at=datetime.fromisoformat("2026-10-30T12:00:00+00:00"),
        duration_ms=1.0,
    )
    episode = Episode(
        source="synthetic",
        agent="fixture",
        agent_version="saved-agent-version",
        input=case.input,
        status="succeeded",
        output_text="Synthetic answer",
        tool_calls=[call],
    )
    writer.episode(episode)
    output = RunOutput(
        text=episode.output_text,
        episode_id=episode.id,
        tool_trace_complete=True,
        tool_trace=[call],
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "diagnostics___get_machine_context",
                    "description": "Pinned description",
                    "parameters": {
                        "type": "object",
                        "properties": {"machine_id": {"type": "string"}},
                        "required": ["machine_id"],
                    },
                },
            }
        ],
    )
    writer.attempt(case, 1, output)
    writer.completed(
        CaseResult(
            case_id=case.id,
            input=case.input,
            split=case.split,
            scores={"exact": 1.0},
            output=output,
        )
    )
    writer.finish()
    return tmp_path


def test_disk_mapping_preserves_pinned_versions_ground_truth_and_tool_results(saved_run):
    publication = eval_publish.publication_from_record(saved_run)
    assert publication.metadata["revision"] == "saved-agent-revision"
    assert publication.metadata["harness_revision"] == "saved-harness-revision"
    assert publication.metadata["agent_version"] == "saved-agent-version"
    assert publication.metadata["skill_version"] == "saved-skill-version"
    assert publication.metadata["dataset_version"] == "saved-dataset-version"
    assert publication.metadata["model"] == "saved-agent-model"
    assert publication.metadata["source"] == "synthetic"
    assert publication.metadata["status"] == "complete"
    assert publication.metadata["metric_parity"] == "unverified"
    row = publication.rows[0]
    assert row.scores == {"exact": 1.0}
    assert row.ground_truth["expected"] == {"machine_id": "M-0001", "failure_mode_id": "FM-01"}
    assert row.ground_truth["truth"] == EvalTruth(
        category="clean", decisive_refs=("EV-000001",)
    ).model_dump(mode="json")
    assert row.tool_calls[0]["result"] == json.dumps({"machine_id": "M-0001", "signals": []})
    assert row.tool_definitions[0]["name"] == row.tool_calls[0]["name"]
    assert row.tool_definitions[0]["description"] == "Pinned description"
    assert row.cohort == "original"


def test_public_publish_command_reads_disk_and_does_not_change_records(saved_run, monkeypatch):
    before = {path: path.read_bytes() for path in saved_run.rglob("*") if path.is_file()}
    submissions = []

    def publish(publication, **kwargs):
        submissions.append((publication, kwargs))
        return "https://example.test/report"

    monkeypatch.setattr(eval_publish, "publish", publish)
    monkeypatch.setattr(
        PlatformSettings,
        "from_env",
        lambda: SimpleNamespace(
            foundry_project_endpoint="configured-endpoint", model_deployment="configured-judge"
        ),
    )
    result = CliRunner().invoke(app, ["--no-azd", "eval", "publish", str(saved_run)])
    assert result.exit_code == 0, result.output
    assert "https://example.test/report" in result.output
    assert submissions[0][0].metadata["model"] == "saved-agent-model"
    assert submissions[0][1] == {
        "endpoint": "configured-endpoint",
        "model": "configured-judge",
    }
    assert before == {path: path.read_bytes() for path in saved_run.rglob("*") if path.is_file()}


def test_public_publish_reports_failure_without_changing_saved_gate(saved_run, monkeypatch):
    def publish(*args, **kwargs):
        raise foundry.FoundryEvalError("synthetic publisher failure")

    monkeypatch.setattr(eval_publish, "publish", publish)
    monkeypatch.setattr(
        PlatformSettings,
        "from_env",
        lambda: SimpleNamespace(foundry_project_endpoint="unused", model_deployment="judge"),
    )
    before = {path: path.read_bytes() for path in saved_run.rglob("*") if path.is_file()}
    result = CliRunner().invoke(app, ["--no-azd", "eval", "publish", str(saved_run)])
    assert result.exit_code != 0
    assert "synthetic publisher failure" in result.output
    assert before == {path: path.read_bytes() for path in saved_run.rglob("*") if path.is_file()}
    assert read_run(saved_run).failures == []


def test_missing_record_is_rejected_before_publication(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("No publication is allowed without a readable run")

    monkeypatch.setattr(eval_publish, "publish", unexpected)
    result = CliRunner().invoke(app, ["--no-azd", "eval", "publish", str(tmp_path)])
    assert result.exit_code != 0


def test_captured_empty_tool_definitions_do_not_fall_back_to_run_definitions(
    saved_run, monkeypatch
):
    record = read_run(saved_run)
    record.manifest.metadata.tool_definitions = record.result.cases[0].output.tool_definitions
    record.result.cases[0].output.tool_definitions = []
    monkeypatch.setattr(eval_publish, "read_run", lambda _: record)
    publication = eval_publish.publication_from_record(saved_run)
    assert publication.rows[0].tool_definitions == []
    with pytest.raises(foundry.FoundryEvalError, match="not captured"):
        foundry.publish(publication, endpoint="unused", model="judge")


def test_plumbing_only_record_marks_metric_parity_blocked(saved_run, monkeypatch):
    record = read_run(saved_run)
    record.result.cases[0].scores = {}
    record.result.cases[0].output.failure = RunError(kind="plumbing", code="timeout")
    monkeypatch.setattr(eval_publish, "read_run", lambda _: record)
    publication = eval_publish.publication_from_record(saved_run)
    assert publication.metadata["metric_parity"] == "blocked:sparse_or_plumbing"


def test_standalone_publish_handles_unexpected_adapter_failure(saved_run, monkeypatch):
    def fail(_):
        raise RuntimeError("unexpected adapter failure")

    monkeypatch.setattr(eval_publish, "publish_record", fail)
    result = CliRunner().invoke(app, ["--no-azd", "eval", "publish", str(saved_run)])
    assert result.exit_code == 2
    assert "unexpected adapter failure" in result.output
    assert read_run(saved_run).failures == []
