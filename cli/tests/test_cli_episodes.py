from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
from typer.testing import CliRunner

from cs_platform.episodes import Episode, Feedback, ToolCall
from csai import app as cli
from csai.platform import PlatformApiError, PlatformClient
from platform_api.api import EpisodeSummary

if TYPE_CHECKING:
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


@pytest.mark.parametrize("private_mode", ["true", "false"])
@pytest.mark.parametrize("forbidden", [False, True])
def test_platform_access_error_explains_private_access(
    monkeypatch: pytest.MonkeyPatch, private_mode: str, *, forbidden: bool
) -> None:
    monkeypatch.setenv("AZURE_PRIVATE_NETWORKING", private_mode)

    def failed_request(
        self: httpx.Client, method: str, url: str, **kwargs: object
    ) -> httpx.Response:
        if forbidden:
            return httpx.Response(403, text="Access denied")
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx.Client, "request", failed_request)
    client = PlatformClient("https://api.example/api", "synthetic-key")
    with pytest.raises(PlatformApiError, match="403" if forbidden else "ConnectError") as error:
        client.list_episodes()
    assert ("jump host" in str(error.value)) == (private_mode == "true")
