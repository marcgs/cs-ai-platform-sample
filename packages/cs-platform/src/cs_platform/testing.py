"""Test doubles for agents built on the platform.

``ScriptedChatClient`` returns scripted assistant turns instead of calling a model. Because it
includes Agent Framework's ``FunctionInvocationLayer``, function calls in a turn are executed
by the framework exactly as with a real model, so tools, middleware and episode capture run
for real.
"""

from typing import TYPE_CHECKING, Any

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class ScriptedChatClient(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    """Returns one scripted assistant turn per model call; records what it was sent."""

    def __init__(
        self, turns: Sequence[Sequence[Content]], usage: Mapping[str, int] | None = None
    ) -> None:
        super().__init__()
        self._turns = list(turns)
        self._usage = dict(usage or {})
        self.requests: list[list[Message]] = []

    @property
    def final_usage(self) -> Any:
        return dict(self._usage)

    def _next_contents(self, messages: Sequence[Message]) -> list[Content]:
        self.requests.append(list(messages))
        contents = list(self._turns.pop(0))
        if self._usage and not self._turns:
            contents.append(Content.from_usage(self.final_usage))
        return contents

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
    """A scripted function call, as a model would emit it."""
    return Content.from_function_call(call_id, name, arguments=arguments)


def text(value: str) -> Content:
    """A scripted text answer."""
    return Content.from_text(value)
