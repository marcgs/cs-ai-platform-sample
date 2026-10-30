import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.responses import InMemoryResponseProvider
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.identity import CredentialUnavailableError
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
from csai import platform as client_module
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
            return httpx.Response(404, json={"error": f"episode {EPISODE_ID} not found"})
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
@pytest.mark.parametrize("answer", ["report", ""])
async def test_hosted_target_carries_real_protocol_identity(
    monkeypatch: pytest.MonkeyPatch, failed: bool, answer: str
) -> None:
    store = InMemoryEpisodeStore()
    agent = build_agent(
        AgentSpec(name="rca-agent", version="1", description="test", instructions="Answer"),
        client=ScriptedChatClient([] if failed else [[text(answer)] for _ in range(2)]),
        store=store,
    )
    host = ResponsesHostServer(
        agent,
        prepare_options=prepare_episode_options,
        response_store=InMemoryResponseProvider(),
        configure_observability=None,
    )

    def handle(request: httpx.Request) -> httpx.Response:
        episode = asyncio.run(store.get(request.url.path.rsplit("/", 1)[1]))
        return httpx.Response(200, json=episode.model_dump(mode="json"))

    client = PlatformClient("http://test", "offline")
    client._http.close()
    api_http = httpx.Client(transport=httpx.MockTransport(handle), base_url="http://test/")
    client._http = api_http
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(PlatformClient, "from_env", factory)
    captured: list[Episode] = []
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
        run = targets.hosted_target(
            targets.AGENTS["rca"], "http://test/responses", credential, on_episode=captured.append
        )
        outputs = [
            await run(EvalCase(id="same", input="M-0001: identical input", expected={}))
            for _ in range(2)
        ]
    await asyncio.to_thread(api_http.close)
    factory.assert_called_once()
    assert len(captured) == 2
    for output, episode in zip(outputs, captured, strict=True):
        assert output.response_id
        assert output.episode_id == hosted_episode_id(output.response_id) == episode.id
        assert episode.hosted_response_id == output.response_id
        assert (output.error is not None) == failed
        assert episode.status == ("failed" if failed else "succeeded")
        if not failed:
            assert output.failure is not None
            assert output.failure.kind == "unparseable"


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("tool_calls", [[], ["get_logbook"]])
def test_diagnose_displays_verified_identity_for_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, failed: bool, tool_calls: list[str]
) -> None:
    output = RunOutput(
        text=None if failed else "report",
        error="model unavailable" if failed else None,
        response_id=RESPONSE_ID,
        episode_id=EPISODE_ID,
        tool_calls=tool_calls,
    )

    async def run(_: EvalCase) -> RunOutput:
        return output

    monkeypatch.setattr(cli, "make_target", lambda *_, **__: run)
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
    expected_tools = ", ".join(tool_calls) or ("unavailable" if failed else "none")
    assert f"Tool calls: {expected_tools}" in result.output
    if failed:
        assert "model unavailable" in result.output


def test_missing_identity_never_searches_recent_episodes(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        pytest.fail("No platform call is safe without an exact response identity")

    monkeypatch.setattr(PlatformClient, "from_env", forbidden)
    assert "identifier missing" in cli.describe_correlation(RunOutput())


@pytest.mark.parametrize("mismatched", [False, True])
def test_captured_correlation_avoids_a_second_credential_lookup(
    monkeypatch: pytest.MonkeyPatch, mismatched: bool
) -> None:
    def forbidden() -> None:
        pytest.fail("A captured episode does not need another credential lookup")

    monkeypatch.setattr(PlatformClient, "from_env", forbidden)
    episode = recorded(id="other" if mismatched else EPISODE_ID)
    message = cli.describe_correlation(
        RunOutput(episode_id=EPISODE_ID, response_id=RESPONSE_ID), episode=episode
    )
    assert ("exact response verified" in message) == (not mismatched)
    assert ("unverified:" in message) == mismatched


def test_missing_persistence_is_not_claimed_as_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    class Missing:
        def wait_for_episode(self, episode_id: str, response_id: str) -> None:
            assert (episode_id, response_id) == (EPISODE_ID, RESPONSE_ID)

    monkeypatch.setattr(PlatformClient, "from_env", classmethod(lambda _: Missing()))
    message = cli.describe_correlation(RunOutput(episode_id=EPISODE_ID, response_id=RESPONSE_ID))
    assert "unverified:" in message
    assert "persistence may be delayed or failed" in message
    assert "agent logs" in message
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


@pytest.mark.parametrize(
    "body",
    [
        b"<html>Route not found</html>",
        b"",
        b'{"error":"not found"}',
        b'{"error":"episode another-id not found"}',
    ],
)
def test_route_and_configuration_404s_are_unverified_not_pending(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, content=body)

    client = PlatformClient("http://test", "offline")
    client._http.close()
    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://test/") as http:
        client._http = http
        monkeypatch.setattr(PlatformClient, "from_env", classmethod(lambda _: client))
        message = cli.describe_correlation(
            RunOutput(episode_id=EPISODE_ID, response_id=RESPONSE_ID)
        )
    assert "unverified:" in message
    assert "not persisted yet" not in message
    assert calls == 1


@pytest.mark.parametrize(
    "failure",
    [
        "credential-init",
        "credential-config",
        "credential-unavailable",
        "credential-auth",
        "credential-network",
        "arm-network",
        "arm-invalid-url",
        "arm-status",
        "key-invalid-json",
        "key-missing",
        "key-empty",
        "episode-invalid-json",
        "episode-invalid-schema",
        "episode-network",
    ],
)
def test_client_failures_preserve_both_ids_and_original_host_error(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    for name in client_module.REQUIRED:
        monkeypatch.setenv(name, "offline")
    monkeypatch.setenv("PLATFORM_API_ENDPOINT", "http://test/")
    credential = MagicMock()
    credential.__enter__.return_value = credential
    credential.get_token.return_value = AccessToken("offline", 0)
    if failure.startswith("credential-"):
        error_type = {
            "credential-init": CredentialUnavailableError,
            "credential-config": ValueError,
            "credential-unavailable": CredentialUnavailableError,
            "credential-auth": ClientAuthenticationError,
            "credential-network": ServiceRequestError,
        }[failure]
        credential.get_token.side_effect = error_type("private credential details")

    def create_credential() -> MagicMock:
        if failure == "credential-init":
            raise CredentialUnavailableError("private credential details")
        if failure == "credential-config":
            raise ValueError("private credential configuration")
        return credential

    monkeypatch.setattr(client_module, "DefaultAzureCredential", create_credential)

    def key_response(*_: object, **__: object) -> httpx.Response:
        if failure == "arm-network":
            raise httpx.ConnectError("private ARM details")
        if failure == "arm-invalid-url":
            raise httpx.InvalidURL("private ARM URL details")
        if failure == "arm-status":
            return httpx.Response(403)
        if failure == "key-invalid-json":
            return httpx.Response(200, content=b"not json")
        keys = (
            {}
            if failure == "key-missing"
            else {"default": "" if failure == "key-empty" else "offline"}
        )
        return httpx.Response(200, json={"functionKeys": keys})

    monkeypatch.setattr(httpx, "post", key_response)

    async def run(_: EvalCase) -> RunOutput:
        return RunOutput(
            error="original hosted failure",
            response_id=RESPONSE_ID,
            episode_id=EPISODE_ID,
        )

    monkeypatch.setattr(cli, "make_target", lambda *_, **__: run)

    def episode_response(request: httpx.Request) -> httpx.Response:
        if failure == "episode-network":
            raise httpx.ReadTimeout("private episode network details", request=request)
        if failure == "episode-invalid-json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, json={"id": EPISODE_ID, "private": "payload details"})

    with httpx.Client(
        transport=httpx.MockTransport(episode_response), base_url="http://test/"
    ) as http:
        monkeypatch.setattr(httpx, "Client", lambda **_: http)
        result = CliRunner().invoke(cli.app, ["--no-azd", "diagnose", "M-0001: identical input"])
    assert result.exit_code == 1, result.output
    assert f"Response: {RESPONSE_ID}" in result.output
    assert f"Episode: {EPISODE_ID}" in result.output
    assert "unverified:" in result.output
    assert "original hosted failure" in result.output
    assert "Tool calls: unavailable" in result.output
    assert "private" not in result.output
    assert "not persisted yet" not in result.output


@pytest.mark.parametrize(
    "endpoint", ["https://example.invalid:invalid", "https://example.invalid/\n"]
)
def test_invalid_endpoint_preserves_ids_and_original_host_error(
    monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    for name in client_module.REQUIRED:
        monkeypatch.setenv(name, "offline")
    monkeypatch.setenv("PLATFORM_API_ENDPOINT", endpoint)
    monkeypatch.setattr(client_module, "function_key", lambda *_: "offline")

    async def run(_: EvalCase) -> RunOutput:
        return RunOutput(
            error="original hosted failure",
            response_id=RESPONSE_ID,
            episode_id=EPISODE_ID,
        )

    monkeypatch.setattr(cli, "make_target", lambda *_, **__: run)
    result = CliRunner().invoke(cli.app, ["--no-azd", "diagnose", "M-0001: identical input"])
    assert result.exit_code == 1, result.output
    assert f"Response: {RESPONSE_ID}" in result.output
    assert f"Episode: {EPISODE_ID}" in result.output
    assert "unverified: Invalid platform API endpoint" in result.output
    assert "original hosted failure" in result.output
