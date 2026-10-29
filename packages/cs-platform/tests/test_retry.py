import asyncio
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx2 as httpx
import pytest
from agent_framework import ChatResponse, ChatResponseUpdate, Content, ResponseStream, tool
from agent_framework.exceptions import ChatClientException
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import AzureCliCredential
from openai import AsyncOpenAI, RateLimitError

from cs_platform.episodes import InMemoryEpisodeStore
from cs_platform.factory import build_agent, foundry_client
from cs_platform.retry import ModelRetryPolicy
from cs_platform.settings import PlatformSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cs_platform.spec import AgentSpec


def rate_limit(headers: dict[str, str] | None = None) -> RateLimitError:
    return RateLimitError(
        "rate limited",
        response=httpx.Response(
            429, headers=headers, request=httpx.Request("POST", "https://model.invalid")
        ),
        body=None,
    )


@pytest.fixture
def sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    sleeper = AsyncMock()
    monkeypatch.setattr("cs_platform.retry.asyncio.sleep", sleeper)
    return sleeper


@pytest.mark.parametrize(
    ("headers", "delay"),
    [
        ({"retry-after": "2"}, 2),
        ({"retry-after-ms": "25"}, 0.025),
        ({"x-ms-retry-after-ms": "50"}, 0.05),
        ({"retry-after": "0"}, 0),
        ({"retry-after": "-1"}, 0),
    ],
)
async def test_server_delay_and_wrapped_recovery(
    headers: dict[str, str], delay: float, sleep: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    inner = rate_limit(headers)
    error = ChatClientException("SDK wrapper", inner_exception=inner)
    error.__cause__ = inner
    operation = AsyncMock(side_effect=[error, "ok"])
    assert await ModelRetryPolicy().response(operation) == "ok"
    sleep.assert_awaited_once_with(delay)
    assert operation.await_count == 2
    assert caplog.records[0].__dict__["retry.will_retry"] is True


async def test_http_date_delay(sleep: AsyncMock) -> None:
    future = datetime.now(UTC) + timedelta(seconds=20)
    operation = AsyncMock(
        side_effect=[rate_limit({"retry-after": format_datetime(future, usegmt=True)}), "ok"]
    )
    await ModelRetryPolicy().response(operation)
    assert sleep.await_args is not None
    assert 18 < sleep.await_args.args[0] <= 20


@pytest.mark.parametrize("header", ["invalid", "nan", "inf"])
async def test_invalid_delay_uses_bounded_jitter(header: str, sleep: AsyncMock) -> None:
    operation = AsyncMock(side_effect=rate_limit({"retry-after": header}))
    with pytest.raises(RateLimitError):
        await ModelRetryPolicy().response(operation)
    assert operation.await_count == 4
    for args, maximum in zip(sleep.await_args_list, [1, 2, 4], strict=True):
        assert maximum / 2 <= args.args[0] <= maximum


@pytest.mark.parametrize("headers", [{"retry-after": "121"}, {"x-should-retry": "false"}])
async def test_server_delay_budget_or_opt_out_terminates(
    headers: dict[str, str], sleep: AsyncMock
) -> None:
    operation = AsyncMock(side_effect=rate_limit(headers))
    with pytest.raises(RateLimitError):
        await ModelRetryPolicy().response(operation)
    assert operation.await_count == 1
    sleep.assert_not_awaited()


async def test_cumulative_wait_budget(sleep: AsyncMock) -> None:
    operation = AsyncMock(side_effect=rate_limit({"retry-after": "70"}))
    with pytest.raises(RateLimitError):
        await ModelRetryPolicy().response(operation)
    assert operation.await_count == 2
    sleep.assert_awaited_once_with(70)


@pytest.mark.parametrize("error", [ValueError("invalid"), RuntimeError("unavailable")])
async def test_non_rate_limits_are_not_retried(error: Exception, sleep: AsyncMock) -> None:
    operation = AsyncMock(side_effect=error)
    with pytest.raises(type(error)):
        await ModelRetryPolicy().response(operation)
    assert operation.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize("during_wait", [False, True])
async def test_cancellation_propagates(during_wait: bool, sleep: AsyncMock) -> None:
    operation = AsyncMock(side_effect=rate_limit() if during_wait else asyncio.CancelledError())
    sleep.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ModelRetryPolicy().response(operation)
    assert operation.await_count == 1


@pytest.mark.parametrize("emitted", [False, True])
async def test_stream_retry_stops_at_first_update(emitted: bool, sleep: AsyncMock) -> None:
    attempts = 0

    def operation() -> ResponseStream[ChatResponseUpdate, ChatResponse]:
        nonlocal attempts
        attempts += 1

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            if emitted:
                yield ChatResponseUpdate()  # Even metadata-only output makes replay unsafe.
            if attempts == 1:
                raise rate_limit({"retry-after": "0"})
            yield ChatResponseUpdate(contents=[Content.from_text("ok")], role="assistant")

        return ResponseStream(updates(), finalizer=ChatResponse.from_updates)

    response = ModelRetryPolicy().stream(operation)
    if emitted:
        with pytest.raises(RateLimitError):
            await response.get_final_response()
        assert attempts == 1
        sleep.assert_not_awaited()
    else:
        assert (await response.get_final_response()).text == "ok"
        assert attempts == 2


async def test_stream_close_releases_provider_and_preserves_finalizer() -> None:
    closed = False

    def operation() -> ResponseStream[ChatResponseUpdate, ChatResponse]:
        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            nonlocal closed
            try:
                yield ChatResponseUpdate(contents=[Content.from_text("ok")])
            finally:
                closed = True

        return ResponseStream(
            updates(),
            finalizer=lambda _: ChatResponse(
                messages=[], additional_properties={"provider_finalized": True}
            ),
        )

    policy = ModelRetryPolicy()
    stream = policy.stream(operation)
    await anext(stream)
    await stream.close()
    assert closed
    result = await policy.stream(operation).get_final_response()
    assert result.additional_properties["provider_finalized"]


async def test_stream_wait_is_cancellable(sleep: AsyncMock) -> None:
    attempts = 0

    def operation() -> ResponseStream[ChatResponseUpdate, ChatResponse]:
        nonlocal attempts
        attempts += 1

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            raise rate_limit()
            yield ChatResponseUpdate()

        return ResponseStream(updates(), finalizer=ChatResponse.from_updates)

    sleep.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ModelRetryPolicy().stream(operation).get_final_response()
    assert attempts == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", [429, 400, 401, 500])
async def test_real_sdk_exhaustion_records_one_failed_episode(
    spec: AgentSpec,
    monkeypatch: pytest.MonkeyPatch,
    sleep: AsyncMock,
    stream: bool,
    status: int,
) -> None:
    requests = 0

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            status, headers={"retry-after": "0"}, json={"error": {"message": "offline failure"}}
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http,
        AsyncOpenAI(api_key="offline", http_client=http) as sdk,
        AzureCliCredential() as credential,
    ):
        monkeypatch.setattr(AIProjectClient, "get_openai_client", lambda *_a, **_kw: sdk)
        settings = PlatformSettings(
            foundry_project_endpoint="https://project.invalid", model_deployment="test-model"
        )
        client = foundry_client(settings, credential)
        assert sdk.max_retries == 0
        store = InMemoryEpisodeStore()
        agent = build_agent(spec, client=client, store=store)
        with pytest.raises(ChatClientException):
            await (
                agent.run("offline test", stream=True).get_final_response()
                if stream
                else agent.run("offline test")
            )
        [episode] = await store.list()
        assert episode.status == "failed"
        assert episode.error
        assert "ChatClientException" in episode.error
        assert "offline failure" in episode.error
        assert requests == (4 if status == 429 else 1)
        await client.project_client.close()


@pytest.mark.parametrize("stream", [False, True])
async def test_real_tool_loop_retries_only_the_failed_turn(
    spec: AgentSpec, monkeypatch: pytest.MonkeyPatch, sleep: AsyncMock, stream: bool
) -> None:
    requests = 0
    tool_calls = 0

    @tool
    def get_status() -> str:
        """Return synthetic machine status."""
        nonlocal tool_calls
        tool_calls += 1
        return "healthy"

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 2:
            return httpx.Response(
                429, headers={"retry-after": "0"}, json={"error": {"message": "try again"}}
            )
        output = (
            [
                {
                    "type": "function_call",
                    "name": "get_status",
                    "call_id": "call-1",
                    "arguments": "{}",
                }
            ]
            if requests == 1
            else [
                {
                    "type": "message",
                    "id": "message-1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "done", "annotations": []}],
                }
            ]
        )
        response = {
            "id": f"response-{requests}",
            "object": "response",
            "created_at": 1,
            "model": "test-model",
            "status": "completed",
            "output": output,
        }
        if not stream:
            return httpx.Response(200, json=response)
        events = (
            [
                {"type": "response.output_item.added", "output_index": 0, "item": output[0]},
                {
                    "type": "response.function_call_arguments.done",
                    "output_index": 0,
                    "item_id": "tool-1",
                    "arguments": "{}",
                },
            ]
            if requests == 1
            else [
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "item_id": "message-1",
                    "delta": "done",
                    "logprobs": [],
                }
            ]
        )
        events.append({"type": "response.completed", "response": response})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(
                f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': i})}\n\n"
                for i, event in enumerate(events)
            ),
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http,
        AsyncOpenAI(api_key="offline", http_client=http) as sdk,
        AzureCliCredential() as credential,
    ):
        monkeypatch.setattr(AIProjectClient, "get_openai_client", lambda *_a, **_kw: sdk)
        client = foundry_client(
            PlatformSettings(
                foundry_project_endpoint="https://project.invalid", model_deployment="test-model"
            ),
            credential,
        )
        store = InMemoryEpisodeStore()
        agent = build_agent(spec, client=client, store=store, tools=[get_status])
        response = (
            await agent.run("offline test", stream=True).get_final_response()
            if stream
            else await agent.run("offline test")
        )
        assert response.text == "done"
        assert requests == 3
        assert tool_calls == 1
        [episode] = await store.list()
        assert episode.status == "succeeded"
        assert episode.error is None
        assert len(episode.tool_calls) == 1
        await client.project_client.close()
