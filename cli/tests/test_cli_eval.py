from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from cs_platform.evals import RunOutput
from cs_platform.evidence import Evidence
from csai import app as cli
from diagnostics_mcp.tools import TOOL_NAMES
from rca_agent.report import Hypothesis, RcaReport

if TYPE_CHECKING:
    from cs_platform.evals import EvalCase, Target

runner = CliRunner()


def answering(correct: bool) -> Any:
    """A local_target replacement that answers every case right (or wrong) with real refs."""

    def factory(*_: object) -> Target:
        async def run(case: EvalCase) -> RunOutput:
            mode = case.expected["failure_mode"] if correct else "FM-99"
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
                        evidence=[
                            Evidence(source="lookup_error_code", ref="EC-2101", excerpt="...")
                        ],
                        recommended_checks=[],
                    )
                ],
                missing_information=[],
            )
            return RunOutput(value=report, tool_calls=list(TOOL_NAMES))

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


def test_hosted_target_needs_a_deployed_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RCA_AGENT_RESPONSES_ENDPOINT", raising=False)
    result = runner.invoke(cli.app, ["--no-azd", "eval", "rca", "--target", "hosted"])
    assert result.exit_code == 2
    assert "AGENT_RCA_AGENT_RESPONSES_ENDPOINT is not set" in result.output
