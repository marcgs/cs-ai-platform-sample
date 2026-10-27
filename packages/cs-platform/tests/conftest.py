"""Test doubles: a scripted chat client that drives the real Agent Framework tool loop."""

from typing import TYPE_CHECKING, Any

import pytest
from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)

from cs_platform.spec import AgentSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class ScriptedChatClient(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    """Returns one scripted assistant turn per model call; records what it was sent.

    Because it includes ``FunctionInvocationLayer``, function-call contents in a turn are
    executed by the framework, exactly as with a real model.
    """

    def __init__(self, turns: Sequence[Sequence[Content]], usage: Mapping[str, int] | None = None):
        super().__init__()
        self._turns = list(turns)
        self._usage = dict(usage or {})
        self.requests: list[list[Message]] = []

    def _next_contents(self, messages: Sequence[Message]) -> list[Content]:
        self.requests.append(list(messages))
        contents = list(self._turns.pop(0))
        if self._usage and not self._turns:
            contents.append(Content.from_usage(self.final_usage))
        return contents

    @property
    def final_usage(self) -> Any:
        return dict(self._usage)

    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> Any:
        last_turn = len(self._turns) == 1
        contents = self._next_contents(messages)
        response_format = options.get("response_format")
        if not stream:
            usage = self.final_usage if self._usage and last_turn else None

            async def respond() -> ChatResponse[Any]:
                return ChatResponse(
                    messages=Message("assistant", contents),
                    response_format=response_format,
                    usage_details=usage,
                )

            return respond()

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            yield ChatResponseUpdate(contents=contents, role="assistant")

        return ResponseStream(
            updates(),
            finalizer=lambda items: ChatResponse.from_updates(
                items, output_format_type=response_format
            ),
        )


def call(name: str, call_id: str = "call-1", **arguments: Any) -> Content:
    return Content.from_function_call(call_id, name, arguments=arguments)


def text(value: str) -> Content:
    return Content.from_text(value)


@pytest.fixture
def spec() -> AgentSpec:
    return AgentSpec(
        name="test-agent",
        version="1.2.3",
        description="Agent under test.",
        instructions="Diagnose the machine.",
    )
