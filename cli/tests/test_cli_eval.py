from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cs_platform.evals import RunOutput
from cs_platform.evidence import Evidence
from cs_platform.factory import build_agent
from cs_platform.spec import AgentSpec
from cs_platform.testing import ScriptedChatClient, text
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
                    item
                    for item in load_seed().historical_cases
                    if item.confirmed_failure_mode == case.expected["failure_mode"]
                )
                evidence.append(
                    Evidence(source="azure_ai_search", ref=history.id, excerpt=history.resolution)
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
