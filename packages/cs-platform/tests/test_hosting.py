import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from agent_framework import Agent, AgentMiddleware
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.responses import InMemoryResponseProvider

from cs_platform.capture import EpisodeCaptureAgentMiddleware
from cs_platform.episodes import Episode, InMemoryEpisodeStore
from cs_platform.hosting import (
    HOSTED_RESPONSE_ID_OPTION,
    hosted_episode_id,
    prepare_episode_options,
)
from cs_platform.testing import ScriptedChatClient, text

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from agent_framework import AgentContext, Message

    from cs_platform.spec import AgentSpec


class CheckingClient(ScriptedChatClient):
    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> Any:
        assert HOSTED_RESPONSE_ID_OPTION not in options
        return super()._inner_get_response(
            messages=messages, stream=stream, options=options, **kwargs
        )


def host(agent: Agent[Any]) -> ResponsesHostServer:
    return ResponsesHostServer(
        agent,
        prepare_options=prepare_episode_options,
        response_store=InMemoryResponseProvider(),
        configure_observability=None,
    )


def terminal(response: httpx.Response, stream: bool) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    if not stream:
        return response.json()
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    return next(
        event["response"]
        for event in reversed(events)
        if event["type"] in {"response.completed", "response.failed"}
    )


@pytest.mark.parametrize("stream", [False, True])
async def test_identical_requests_complete_out_of_order_without_session_collisions(
    spec: AgentSpec, monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockFirst(AgentMiddleware):
        async def process(
            self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
        ) -> None:
            if not entered.is_set():
                entered.set()
                await release.wait()
            await call_next()

    monkeypatch.setenv("FOUNDRY_AGENT_SESSION_ID", "shared-test-session")
    store = InMemoryEpisodeStore()
    agent = Agent(
        CheckingClient([[text("second finished first")], [text("first finished last")]]),
        instructions=spec.instructions,
        middleware=[EpisodeCaptureAgentMiddleware(spec, store), BlockFirst()],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=host(agent)), base_url="http://test"
    ) as client:
        body = {
            "input": "M-0001: identical input",
            "store": False,
            "stream": stream,
            HOSTED_RESPONSE_ID_OPTION: "caller-cannot-spoof-this",
        }
        first = asyncio.create_task(client.post("/responses", json=body))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            second = terminal(await client.post("/responses", json=body), stream)
            [second_episode] = await store.list()
            assert second_episode.output_text == "second finished first"
        finally:
            release.set()
        first_response = terminal(await first, stream)

    first_episode = await store.get(hosted_episode_id(first_response["id"]))
    assert first_response["id"] != second["id"]
    assert first_response["agent_session_id"] == second["agent_session_id"] == "shared-test-session"
    assert first_episode.hosted_response_id == first_response["id"]
    assert second_episode.hosted_response_id == second["id"]
    assert second_episode.id == hosted_episode_id(second["id"])
    assert first_episode.output_text == "first finished last"
    assert first_episode.input == second_episode.input
    assert first_episode.completed_at is not None
    assert second_episode.completed_at is not None
    assert first_episode.completed_at > second_episode.completed_at
    # Framework additional_properties are not projected into the Responses payload.
    assert "episode_id" not in first_response
    assert "episode_id" not in first_response.get("metadata", {})


@pytest.mark.parametrize("stream", [False, True])
async def test_host_failure_preserves_exact_response_identity(
    spec: AgentSpec, stream: bool
) -> None:
    store = InMemoryEpisodeStore()
    agent = Agent(
        CheckingClient([]),
        middleware=[EpisodeCaptureAgentMiddleware(spec, store)],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=host(agent)), base_url="http://test"
    ) as client:
        response = terminal(
            await client.post(
                "/responses", json={"input": "same", "store": False, "stream": stream}
            ),
            stream,
        )
    assert response["status"] == "failed"
    episode = await store.get(hosted_episode_id(response["id"]))
    assert episode.hosted_response_id == response["id"]
    assert episode.status == "failed"


def test_legacy_episode_remains_readable() -> None:
    episode = Episode.model_validate(
        {"id": "legacy", "agent": "rca-agent", "agent_version": "1", "input": "same"}
    )
    assert episode.id == "legacy"
    assert episode.hosted_response_id is None
