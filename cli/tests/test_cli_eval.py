import json
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cs_platform.evals import RunOutput, run_suite
from cs_platform.evidence import Evidence
from cs_platform.factory import build_agent
from cs_platform.spec import AgentSpec
from cs_platform.testing import ScriptedChatClient, call, text
from csai import app as cli
from csai import targets
from diagnostics_domain.dataset import load_seed
from diagnostics_mcp.tools import TOOL_NAMES
from rca_agent.report import Hypothesis, RcaReport

if TYPE_CHECKING:
    from cs_platform.evals import EvalCase, Target

runner = CliRunner()


def answering(correct: bool, *, knowledge: bool = True) -> Any:
    """A local_target replacement that answers every case right (or wrong) with real refs."""

    def factory(*_: object) -> Target:
        async def run(case: EvalCase) -> RunOutput:
            mode = case.expected["failure_mode"] if correct else "FM-99"
            evidence = [Evidence(source="lookup_error_code", ref="EC-2101", excerpt="...")]
            if knowledge:
                history = next(
                    (
                        item
                        for item in load_seed().historical_cases
                        if item.confirmed_failure_mode == case.expected["failure_mode"]
                    ),
                    None,
                )
                if history is not None:
                    evidence.append(
                        Evidence(
                            source="azure_ai_search", ref=history.id, excerpt=history.resolution
                        )
                    )
            report = RcaReport(
                machine_id=case.expected["machine_id"],
                summary="...",
                hypotheses=[
                    Hypothesis(
                        rank=1,
                        failure_mode_id=mode,
                        title=mode,
                        root_cause="...",
                        confidence=0.9,
                        evidence=evidence,
                        recommended_checks=[],
                    )
                ],
                missing_information=[],
            )
            calls: list[str] = list(TOOL_NAMES)
            if knowledge:
                calls.append("azure_ai_search")
            return RunOutput(value=report, tool_calls=calls)

        return run

    return factory


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p"
    )


def test_gate_passes_when_metrics_meet_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "local_target", answering(correct=True))
    result = runner.invoke(
        cli.app, ["--no-azd", "eval", "rca", "--case", "SC-001", "--case", "SC-002"]
    )
    assert result.exit_code == 0, result.output
    assert "2 cases" in result.output
    assert "Gate passed." in result.output


def test_gate_fails_with_exit_code_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(cli, "local_target", answering(correct=False))
    results = tmp_path / "results.jsonl"
    result = runner.invoke(
        cli.app, ["--no-azd", "eval", "rca", "--case", "SC-001", "--output", str(results)]
    )
    assert result.exit_code == 1
    assert "hit_at_1: 0.00 < 0.80" in result.output
    assert '"case_id": "SC-001"' in results.read_text()


def test_gate_rejects_correct_answers_without_historical_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "local_target", answering(correct=True, knowledge=False))
    result = runner.invoke(cli.app, ["--no-azd", "eval", "rca", "--case", "SC-001"])
    assert result.exit_code == 1
    assert "used_knowledge: 0.00 < 0.70" in result.output
    assert "hit_at_1: 0.00" not in result.output


def test_hosted_target_needs_a_deployed_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RCA_AGENT_RESPONSES_ENDPOINT", raising=False)
    result = runner.invoke(cli.app, ["--no-azd", "eval", "rca", "--target", "hosted"])
    assert result.exit_code == 2
    assert "AGENT_RCA_AGENT_RESPONSES_ENDPOINT is not set" in result.output


@pytest.mark.parametrize(
    "arguments",
    [
        ["diagnose", "M-0001: check", "--target", "local"],
        ["eval", "rca", "--target", "local", "--case", "SC-001"],
    ],
)
def test_local_commands_bootstrap_telemetry(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    def create(*_: object, **kwargs: Any) -> Any:
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient([[text("done")]]),
            store=kwargs["store"],
        )

    configure = Mock()
    monkeypatch.setattr(targets, "configure_telemetry", configure)
    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    result = runner.invoke(cli.app, ["--no-azd", *arguments])
    assert result.exit_code in {0, 1}, result.output
    configure.assert_called_once()
    assert configure.call_args.kwargs["service_name"] == "rca-agent-local"


def test_repeats_split_and_provenance_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from cs_platform.evals import assign_splits

    monkeypatch.setattr(cli, "local_target", answering(correct=True))
    monkeypatch.setattr(cli, "run_suite", partial(run_suite, retries=0))
    cases = assign_splits(targets.AGENTS["rca"].load_suite().cases)
    train = {case.id for case in cases if case.split == "train"}
    output = tmp_path / "results.jsonl"
    result = runner.invoke(
        cli.app,
        [
            "--no-azd",
            "eval",
            "rca",
            "--repeats",
            "3",
            "--split",
            "train",
            "--agent-revision",
            "fixed-baseline",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == len(train) * 3
    assert {record["case_id"] for record in records} == train
    assert {record["repeat"] for record in records} == {1, 2, 3}
    assert all(record["output"]["error"] is None for record in records)
    assert all(record["output"]["attempts"] == 1 for record in records)
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["run"]["agent_revision"] == "fixed-baseline"
    assert summary["run"]["harness_revision"]
    assert "95% CI" in result.output
    assert output.with_suffix(".html").exists()
    assert len(list((tmp_path / "results-transcripts").glob("*.json"))) == len(records)


@pytest.mark.parametrize(
    "arguments",
    [
        ["eval", "rca", "--repeats", "0"],
        ["eval", "rca", "--split", "unknown"],
        ["eval", "rca", "--case", "does-not-exist"],
        ["eval", "rca", "--target", "hosted", "--episodes-output", "unused.jsonl"],
        ["diagnose", "M-0001", "--target", "hosted", "--episodes-output", "unused.jsonl"],
    ],
)
def test_eval_rejects_invalid_selection_and_hosted_exports(arguments: list[str]) -> None:
    result = runner.invoke(cli.app, ["--no-azd", *arguments])
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize("fails", [False, True])
def test_real_local_episode_export_and_full_tool_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, fails: bool
) -> None:
    from agent_framework import tool

    @tool
    def machine_status(machine_id: str) -> str:
        """Return synthetic machine status."""
        return f"{machine_id}: stable"

    def create(*_: object, **kwargs: Any) -> Any:
        turns = [[call("machine_status", machine_id="M-0001")]]
        if not fails:
            turns.append([text("done")])
        return build_agent(
            AgentSpec(name="test", version="1", description="test", instructions="test"),
            client=ScriptedChatClient(turns),
            store=kwargs["store"],
            tools=[machine_status],
        )

    monkeypatch.setattr(targets, "configure_telemetry", lambda *_, **__: None)
    monkeypatch.setitem(targets.AGENTS, "rca", replace(targets.AGENTS["rca"], create=create))
    path = tmp_path / "episodes.jsonl"
    result = runner.invoke(
        cli.app,
        [
            "--no-azd",
            "diagnose",
            "M-0001: check",
            "--target",
            "local",
            "--episodes-output",
            str(path),
        ],
    )
    assert result.exit_code == (1 if fails else 0), result.output
    [episode] = [json.loads(line) for line in path.read_text().splitlines()]
    assert episode["source"] == "real"
    assert episode["status"] == ("failed" if fails else "succeeded")
    [tool_call] = episode["tool_calls"]
    assert tool_call["arguments"] == {"machine_id": "M-0001"}
    assert "stable" in tool_call["result"]
    repeated = runner.invoke(
        cli.app,
        [
            "--no-azd",
            "diagnose",
            "M-0001",
            "--target",
            "local",
            "--episodes-output",
            str(path),
        ],
    )
    assert repeated.exit_code == 2


def test_report_only_selection_does_not_evaluate_or_claim_regression_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from cs_platform.evals import EvalCase, EvalSuite, EvalTruth, Thresholds

    def evaluate(case: EvalCase, output: RunOutput) -> dict[str, float]:
        return {"exact": float(output.text == case.expected["answer"])}

    suite = EvalSuite(
        "demo",
        (
            EvalCase(id="SC-001", input="regression", expected={"answer": "yes"}),
            EvalCase(
                id="SC-019",
                input="challenge",
                expected={"answer": "yes"},
                truth=EvalTruth(category="overlapping"),
            ),
        ),
        Thresholds(minimums={"exact": 1.0}),
        (evaluate,),
        gate_case_ids=frozenset({"SC-001"}),
    )

    def factory(*_: object) -> Target:
        async def run(case: EvalCase) -> RunOutput:
            return RunOutput(text="no")

        return run

    monkeypatch.setitem(
        targets.AGENTS, "rca", replace(targets.AGENTS["rca"], load_suite=lambda: suite)
    )
    monkeypatch.setattr(cli, "local_target", factory)
    output = tmp_path / "results.jsonl"
    result = runner.invoke(
        cli.app,
        [
            "--no-azd",
            "eval",
            "rca",
            "--case",
            "SC-019",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Informational run complete; no regression gate evaluated." in result.output
    assert "Gate passed." not in result.output
    assert "Gate failed" not in result.output
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["failures"] == []
    assert summary["gate_metrics"] == {}
    assert summary["gate_case_ids"] == []
    assert summary["metrics"] == {"exact": 0.0}
