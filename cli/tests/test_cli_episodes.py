from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cs_platform.episodes import Episode, Feedback, ToolCall
from cs_platform.evals import RunOutput
from csai import app as cli
from csai.platform import PlatformClient
from platform_api.api import EpisodeSummary

if TYPE_CHECKING:
    from cs_platform.evals import EvalCase, Target
    from platform_api.api import FeedbackRequest

runner = CliRunner()
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
REPORT = {
    "machine_id": "M-0001",
    "summary": "Stage cooling is drifting.",
    "hypotheses": [
        {
            "rank": 1,
            "failure_mode_id": "FM-01",
            "title": "Stage cooling drift",
            "root_cause": "Fouled valve.",
            "confidence": 0.9,
            "evidence": [{"source": "lookup_error_code", "ref": "EC-2101", "excerpt": "..."}],
            "recommended_checks": ["Check flow."],
        }
    ],
    "missing_information": [],
}


class FakePlatform:
    def __init__(self) -> None:
        self.episode = Episode(
            id="ep-1",
            agent="rca-agent",
            agent_version="0.1.0",
            created_at=NOW,
            status="succeeded",
            input="M-0001: alarm",
            output=REPORT,
            tool_calls=[
                ToolCall(
                    name="get_logbook",
                    arguments={"machine_id": "M-0001"},
                    started_at=NOW,
                    duration_ms=12,
                )
            ],
        )

    def list_episodes(self, *, agent: str | None = None, limit: int = 20) -> list[EpisodeSummary]:
        return [EpisodeSummary.of(self.episode)]

    def get_episode(self, episode_id: str) -> Episode:
        return self.episode

    def add_feedback(self, episode_id: str, feedback: FeedbackRequest) -> Episode:
        self.episode.feedback = Feedback(**feedback.model_dump())
        return self.episode


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakePlatform:
    platform = FakePlatform()
    monkeypatch.setattr(PlatformClient, "from_env", classmethod(lambda cls: platform))
    return platform


def test_episodes_list_and_show(fake: FakePlatform) -> None:
    listed = runner.invoke(cli.app, ["--no-azd", "episodes", "list"])
    assert listed.exit_code == 0, listed.output
    assert "ep-1" in listed.output
    assert "tools=1" in listed.output

    shown = runner.invoke(cli.app, ["--no-azd", "episodes", "show", "ep-1"])
    assert shown.exit_code == 0, shown.output
    assert "get_logbook(machine_id=M-0001) 12 ms" in shown.output
    assert "Stage cooling drift [FM-01]" in shown.output


def test_feedback_is_attached(fake: FakePlatform) -> None:
    result = runner.invoke(
        cli.app,
        ["--no-azd", "feedback", "ep-1", "--verdict", "incorrect", "--actual-root-cause", "FM-05"],
    )
    assert result.exit_code == 0, result.output
    assert fake.episode.feedback is not None
    assert fake.episode.feedback.actual_root_cause == "FM-05"
    shown = runner.invoke(cli.app, ["--no-azd", "episodes", "show", "ep-1"])
    assert "incorrect; actual root cause FM-05" in shown.output


def test_diagnose_prints_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(*_: object) -> Target:
        async def run(case: EvalCase) -> RunOutput:
            from rca_agent.report import RcaReport

            return RunOutput(value=RcaReport.model_validate(REPORT), tool_calls=["get_logbook"])

        return run

    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p"
    )
    monkeypatch.setattr(cli, "local_target", factory)
    result = runner.invoke(cli.app, ["--no-azd", "diagnose", "M-0001: alarm", "--target", "local"])
    assert result.exit_code == 0, result.output
    assert "Stage cooling drift [FM-01]" in result.output
    assert "Tool calls: get_logbook" in result.output
