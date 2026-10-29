import time
from typing import Any

import httpx
import pytest
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.responses import InMemoryResponseProvider
from azure.identity.aio import DefaultAzureCredential
from openai import AsyncOpenAI
from typer.testing import CliRunner

from cs_platform.episodes import Episode, InMemoryEpisodeStore
from cs_platform.evals import EvalCase, RunOutput
from cs_platform.factory import build_agent
from cs_platform.hosting import hosted_episode_id, prepare_episode_options
from cs_platform.spec import AgentSpec
from cs_platform.testing import ScriptedChatClient, text
from csai import app as cli
from csai import targets
from csai.platform import PlatformApiError, PlatformClient

RESPONSE_ID = "response-exact"
EPISODE_ID = hosted_episode_id(RESPONSE_ID)


def recorded(**updates: Any) -> Episode:
    return Episode(
        id=EPISODE_ID,
        agent="rca-agent",
        agent_version="1",
        input="M-0001: identical input",
        hosted_response_id=RESPONSE_ID,
    ).model_copy(update=updates)


@pytest.mark.parametrize("available_after", [0, 2, None])
def test_point_reads_handle_delayed_and_missing_persistence(
    monkeypatch: pytest.MonkeyPatch, available_after: int | None
) -> None:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if available_after is None or len(calls) <= available_after:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=recorded().model_dump(mode="json"))

    monkeypatch.setattr(time, "sleep", sleeps.append)
    client = PlatformClient("http://test", "offline")
    client._http.close()
    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://test/") as http:
        client._http = http
        episode = client.wait_for_episode(EPISODE_ID, RESPONSE_ID, attempts=4, interval_s=0.1)
    assert (episode is not None) == (available_after is not None)
    expected_calls = 4 if available_after is None else available_after + 1
    assert len(calls) == expected_calls
    assert sleeps == [0.1] * (expected_calls - 1)
    assert {request.url.path for request in calls} == {f"/episodes/{EPISODE_ID}"}
    assert all(not request.url.query for request in calls)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_polling_does_not_hide_api_failures(status: int) -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "unavailable"})

    client = PlatformClient("http://test", "offline")
    client._http.close()
    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://test/") as http:
        client._http = http
        with pytest.raises(PlatformApiError) as raised:
            client.wait_for_episode(EPISODE_ID, RESPONSE_ID)
    assert raised.value.status_code == status
    assert calls == 1


@pytest.mark.parametrize(
    "updates",
    [{"hosted_response_id": "another-response"}, {"hosted_response_id": None}, {"id": "other"}],
)
def test_polling_rejects_mismatched_and_legacy_records(updates: dict[str, Any]) -> None:
    client = PlatformClient("http://test", "offline")
    client._http.close()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=recorded(**updates).model_dump(mode="json"))
        ),
        base_url="http://test/",
    ) as http:
        client._http = http
        with pytest.raises(PlatformApiError, match="identity does not match"):
            client.wait_for_episode(EPISODE_ID, RESPONSE_ID)


@pytest.mark.parametrize("failed", [False, True])
async def test_hosted_target_carries_real_protocol_identity(
    monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    store = InMemoryEpisodeStore()
    agent = build_agent(
        AgentSpec(name="rca-agent", version="1", description="test", instructions="Answer"),
        client=ScriptedChatClient([] if failed else [[text("report")]]),
        store=store,
    )
    host = ResponsesHostServer(
        agent,
        prepare_options=prepare_episode_options,
        response_store=InMemoryResponseProvider(),
        configure_observability=None,
    )
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=host)) as http,
        # OpenAI accepts legacy httpx clients at runtime but annotates only httpx2.
        AsyncOpenAI(
            base_url="http://test",
            api_key="offline",
            http_client=http,  # pyright: ignore[reportArgumentType]
        ) as sdk,
        DefaultAzureCredential() as credential,
    ):
        monkeypatch.setattr(targets, "AsyncOpenAI", lambda **_: sdk)
        run = targets.hosted_target(targets.AGENTS["rca"], "http://test/responses", credential)
        output = await run(EvalCase(id="same", input="M-0001: identical input", expected={}))
    assert output.response_id
    assert output.episode_id is not None
    assert output.episode_id == hosted_episode_id(output.response_id)
    episode = await store.get(output.episode_id)
    assert episode.hosted_response_id == output.response_id
    assert (output.error is not None) == failed
    assert episode.status == ("failed" if failed else "succeeded")


@pytest.mark.parametrize("failed", [False, True])
def test_diagnose_displays_verified_identity_for_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    output = RunOutput(
        text=None if failed else "report",
        error="model unavailable" if failed else None,
        response_id=RESPONSE_ID,
        episode_id=EPISODE_ID,
    )

    async def run(_: EvalCase) -> RunOutput:
        return output

    monkeypatch.setattr(cli, "make_target", lambda *_: run)
    client = PlatformClient("http://test", "offline")
    client._http.close()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=recorded(status="failed" if failed else "succeeded").model_dump(mode="json"),
            )
        ),
        base_url="http://test/",
    ) as http:
        client._http = http
        monkeypatch.setattr(PlatformClient, "from_env", classmethod(lambda _: client))
        result = CliRunner().invoke(cli.app, ["--no-azd", "diagnose", "M-0001: identical input"])
    assert result.exit_code == (1 if failed else 0), result.output
    assert f"Response: {RESPONSE_ID}" in result.output
    assert f"Episode: {EPISODE_ID}" in result.output
    assert "exact response verified" in result.output
    if failed:
        assert "model unavailable" in result.output


def test_missing_identity_never_searches_recent_episodes(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        pytest.fail("No platform call is safe without an exact response identity")

    monkeypatch.setattr(PlatformClient, "from_env", forbidden)
    assert "identifier missing" in cli.describe_correlation(RunOutput())


def test_missing_persistence_is_not_claimed_as_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    class Missing:
        def wait_for_episode(self, episode_id: str, response_id: str) -> None:
            assert (episode_id, response_id) == (EPISODE_ID, RESPONSE_ID)

    monkeypatch.setattr(PlatformClient, "from_env", classmethod(lambda _: Missing()))
    message = cli.describe_correlation(RunOutput(episode_id=EPISODE_ID, response_id=RESPONSE_ID))
    assert "not persisted yet" in message
    assert "exact response verified" not in message
    assert f"csai episodes show {EPISODE_ID}" in message


def test_network_outage_leaves_identity_explicitly_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    client = PlatformClient("http://test", "offline")
    client._http.close()
    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://test/") as http:
        client._http = http
        monkeypatch.setattr(PlatformClient, "from_env", classmethod(lambda _: client))
        message = cli.describe_correlation(
            RunOutput(episode_id=EPISODE_ID, response_id=RESPONSE_ID)
        )
    assert f"Episode: {EPISODE_ID}" in message
    assert "unverified:" in message
    assert "ConnectError" in message
    assert calls == 1


def test_episode_details_show_host_identity_but_preserve_legacy_output() -> None:
    assert f"Response: {RESPONSE_ID}" in cli.describe_episode(recorded())
    assert not any(
        line.startswith("Response:")
        for line in cli.describe_episode(recorded(hosted_response_id=None))
    )
