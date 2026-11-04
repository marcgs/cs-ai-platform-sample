"""The hosted stream projection, run through the real hosting adapter's output tracker."""

import json
from typing import TYPE_CHECKING, Any

import pytest
from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    ResponseStream,
    tool,
)
from agent_framework_foundry_hosting._responses import _OutputItemTracker
from azure.ai.agentserver.responses.aio.streaming import ResponseEventStream

from cs_platform.episodes import InMemoryEpisodeStore
from cs_platform.settings import PlatformSettings
from rca_agent.agent import create_agent
from rca_agent.hosted_stream import AppendOnlyProjection, HostedStreamError, HostedStreamMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from agent_framework import AgentMiddleware, Message
    from azure.core.credentials_async import AsyncTokenCredential

SETTINGS = PlatformSettings(foundry_project_endpoint="https://example/api/projects/p")
CREDENTIAL: AsyncTokenCredential = None  # type: ignore[assignment]  # unused with injected parts
REPORT = (
    '{"machine_id": "M-0001", "summary": "Unclear.", "hypotheses": [], "missing_information": []}'
)


class StreamingScriptedClient(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    """Streams each scripted turn as several updates, as a Responses model client does."""

    def __init__(self, turns: Sequence[Sequence[Sequence[Content]]]) -> None:
        super().__init__()
        self._turns = list(turns)

    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> Any:
        assert stream, "hosted runs stream"
        turn = self._turns.pop(0)

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            for contents in turn:
                yield ChatResponseUpdate(contents=list(contents), role="assistant")

        return ResponseStream(updates(), finalizer=ChatResponse.from_updates)


def streamed_call(
    call_id: str, name: str, arguments: dict[str, Any], *, deltas: int
) -> list[Content]:
    """Argument deltas, then the full snapshot, as the OpenAI Responses client sends them."""
    text = json.dumps(arguments)
    step = -(-len(text) // deltas) if deltas else 0
    parts = [text[i : i + step] for i in range(0, len(text), step)] if deltas else []
    return [
        *(
            Content.from_function_call(call_id, name, arguments=p, merge_mode="append")
            for p in parts
        ),
        Content.from_function_call(call_id, name, arguments=text, merge_mode="replace"),
    ]


def usage(input_tokens: int, output_tokens: int) -> Content:
    return Content.from_usage(
        {"input_token_count": input_tokens, "output_token_count": output_tokens},
        merge_mode="replace",
    )


@tool
def get_error_events(machine_id: str, hours: int = 72) -> str:
    """Error events in a look-back window."""
    return f"no errors for {machine_id} in {hours}h"


@tool
def get_logbook(machine_id: str, days: int = 30) -> str:
    """Service logbook entries."""
    return f"no entries for {machine_id} in {days}d"


CALLS = [
    ("call-1", "get_error_events", {"machine_id": "M-0001", "hours": 168}),
    ("call-2", "get_logbook", {"machine_id": "M-0001", "days": 14}),
    ("call-3", "get_error_events", {"machine_id": "M-0001", "hours": 24}),
]


def three_rounds() -> list[list[list[Content]]]:
    """Two parallel calls (one fragmented, one snapshot only), one more call, then the answer."""
    (id1, name1, args1), (id2, name2, args2), (id3, name3, args3) = CALLS
    return [
        [
            *([c] for c in streamed_call(id1, name1, args1, deltas=4)),
            *([c] for c in streamed_call(id2, name2, args2, deltas=0)),
            [usage(100, 10)],
        ],
        [*([c] for c in streamed_call(id3, name3, args3, deltas=3)), [usage(150, 15)]],
        [[Content.from_text(REPORT[:20])], [Content.from_text(REPORT[20:])], [usage(200, 20)]],
    ]


async def host(
    middleware: Sequence[AgentMiddleware],
) -> tuple[list[Any], Any, AgentResponse[Any], InMemoryEpisodeStore]:
    """Run the RCA agent and feed its stream to the hosting adapter, as the host server does."""
    store = InMemoryEpisodeStore()
    agent = create_agent(
        SETTINGS,
        CREDENTIAL,
        client=StreamingScriptedClient(three_rounds()),
        store=store,
        tools=[get_error_events, get_logbook],
        middleware=middleware,
    )
    events_stream = ResponseEventStream(response_id="hosted-stream-test")
    events_stream.emit_created()
    events_stream.emit_in_progress()
    tracker = _OutputItemTracker(events_stream)
    stream = agent.run("M-0001: stage drift", stream=True)
    events: list[Any] = []
    async for update in stream:
        events.extend([event async for event in tracker.handle_update(update)])
    events.extend(tracker.close())
    completed = events_stream.emit_completed(usage=tracker.usage)
    final = await stream.get_final_response()
    return events, completed["response"].get("usage"), final, store


def done_arguments(events: list[Any]) -> list[str]:
    return [e["arguments"] for e in events if e["type"] == "response.function_call_arguments.done"]


async def test_host_output_matches_the_final_response_and_the_episode() -> None:
    events, host_usage, final, store = await host([HostedStreamMiddleware()])

    arguments = done_arguments(events)
    assert [json.loads(a) for a in arguments] == [args for _, _, args in CALLS]
    final_arguments = [
        c.arguments for m in final.messages for c in m.contents if c.type == "function_call"
    ]
    assert arguments == final_arguments
    assert (host_usage["input_tokens"], host_usage["output_tokens"]) == (450, 45)
    assert final.usage_details == {"input_token_count": 450, "output_token_count": 45}
    [episode] = await store.list()
    assert episode.usage is not None
    assert (episode.usage.input_tokens, episode.usage.output_tokens) == (450, 45)
    assert [c.name for c in episode.tool_calls] == [name for _, name, _ in CALLS]


async def test_unprojected_host_still_corrupts_snapshots() -> None:
    """Fails once the hosting adapter honors merge_mode; then this module can go."""
    events, host_usage, final, _ = await host([])

    assert done_arguments(events)[0] == json.dumps(CALLS[0][2]) * 2
    assert final.usage_details is not None
    assert host_usage["input_tokens"] > final.usage_details.get("input_token_count", 0)


def call_update(arguments: str, merge_mode: str, call_id: str = "call-1") -> AgentResponseUpdate:
    content = Content.from_function_call(call_id, "f", arguments=arguments, merge_mode=merge_mode)  # type: ignore[arg-type]
    return AgentResponseUpdate(contents=[content])


def projected_arguments(projection: AppendOnlyProjection, update: AgentResponseUpdate) -> list[Any]:
    return [c.arguments for c in projection(update).contents]


def test_a_longer_snapshot_sends_only_the_missing_suffix() -> None:
    projection = AppendOnlyProjection()
    assert projected_arguments(projection, call_update('{"a": ', "append")) == ['{"a": ']
    assert projected_arguments(projection, call_update('{"a": 1}', "replace")) == ["1}"]


def test_an_equivalent_snapshot_in_other_formatting_is_dropped() -> None:
    projection = AppendOnlyProjection()
    projection(call_update('{"a":1}', "append"))
    assert projected_arguments(projection, call_update('{"a": 1}', "replace")) == []


def test_a_divergent_snapshot_fails_instead_of_corrupting() -> None:
    projection = AppendOnlyProjection()
    projection(call_update('{"a": 1', "append"))
    with pytest.raises(HostedStreamError, match="call-1"):
        projection(call_update('{"b": 2}', "replace"))


def test_extending_a_closed_call_fails() -> None:
    projection = AppendOnlyProjection()
    projection(call_update('{"a": ', "append"))
    projection(call_update("{}", "append", call_id="call-2"))
    with pytest.raises(HostedStreamError, match="closed"):
        projection(call_update('{"a": 1}', "replace"))


async def test_a_divergent_snapshot_fails_the_hosted_run() -> None:
    turn = [
        [
            Content.from_function_call(
                "call-1", "get_logbook", arguments='{"machine_id": "M-1', merge_mode="append"
            )
        ],
        [
            Content.from_function_call(
                "call-1", "get_logbook", arguments='{"machine_id": "M-2"}', merge_mode="replace"
            )
        ],
    ]
    agent = create_agent(
        SETTINGS,
        CREDENTIAL,
        client=StreamingScriptedClient([turn]),
        store=InMemoryEpisodeStore(),
        tools=[get_logbook],
        middleware=[HostedStreamMiddleware()],
    )
    with pytest.raises(HostedStreamError):
        async for _ in agent.run("M-0001: incident", stream=True):
            pass
