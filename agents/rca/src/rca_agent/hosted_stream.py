"""Projects the agent's update stream onto the append-only form the hosting adapter reads.

Agent Framework marks each streamed content as an increment (``merge_mode="append"``) or a
full snapshot (``"replace"``): a model client sends tool-call argument deltas and then the
complete arguments, and the tool loop reports usage as cumulative snapshots. The final
``AgentResponse`` honors that. The hosting adapter (``agent-framework-foundry-hosting``
1.0.0b261015 to at least 1.0.0b261030) doesn't for arguments or usage: it appends every
argument string and sums every usage content. Hosted Responses output then repeats each
call's arguments and inflates usage (see ``docs/foundry-findings.md``).

``HostedStreamMiddleware`` rewrites only the updates the host reads, so that appending them
gives the same result as the framework's own merge. The stream records each update before
its transforms run, so the final response, and the episode captured from it, is unchanged.
"""

import copy
import json
from typing import TYPE_CHECKING

from agent_framework import AgentMiddleware, AgentResponseUpdate, Content, UsageDetails

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent_framework import AgentContext

_CALL_TYPES = frozenset({"function_call", "mcp_server_tool_call"})


class HostedStreamError(RuntimeError):
    """A snapshot that an append-only stream can't represent without corrupting output."""


class HostedStreamMiddleware(AgentMiddleware):
    """Registers a fresh ``AppendOnlyProjection`` on every streamed run."""

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        await call_next()
        if context.stream:
            context.stream_update_transforms.append(AppendOnlyProjection())


class AppendOnlyProjection:
    """Turns argument and usage snapshots into the increments that reproduce them.

    Arguments: a snapshot that extends what was already streamed for its call becomes the
    missing suffix, and one that repeats it is dropped. Anything else would need the host to
    take back text it has already sent, so it raises ``HostedStreamError`` instead.

    Usage: each snapshot becomes its difference from the previous total, so the host's sum
    equals the last snapshot, as in the framework's final response.
    """

    def __init__(self) -> None:
        self._arguments: dict[str, str] = {}
        self._open_call: str | None = None
        self._usage: dict[str, int] = {}

    def __call__(self, update: AgentResponseUpdate) -> AgentResponseUpdate:
        contents: list[Content] = []
        for content in update.contents:
            projected = self._project(content)
            if projected is not None:
                contents.append(projected)
        projected_update = copy.copy(update)
        projected_update.contents = contents
        return projected_update

    def _project(self, content: Content) -> Content | None:
        if content.type == "usage":
            return self._project_usage(content)
        if content.type in _CALL_TYPES and content.arguments is not None:
            key = _call_key(content)
            if key is not None:
                return self._project_arguments(content, key)
        self._open_call = None
        return content

    def _project_arguments(self, content: Content, key: str) -> Content | None:
        arguments = _as_text(content.arguments)
        streamed = self._arguments.get(key)
        is_open = self._open_call == key
        self._open_call = key
        if content.merge_mode != "replace":
            self._arguments[key] = (streamed or "") + arguments
            return content
        if streamed is None:
            self._arguments[key] = arguments
            return _with(content, arguments=arguments, merge_mode="append")
        if arguments.startswith(streamed):
            suffix = arguments[len(streamed) :]
            if not suffix:
                return None
            if not is_open:
                raise HostedStreamError(
                    f"Arguments for call {key!r} changed after the host closed its output item."
                )
            self._arguments[key] = arguments
            return _with(content, arguments=suffix, merge_mode="append")
        if _same_json(streamed, arguments):
            return None
        raise HostedStreamError(
            f"Arguments for call {key!r} were replaced by a snapshot that doesn't extend the "
            "streamed text; an append-only Responses stream can't represent that."
        )

    def _project_usage(self, content: Content) -> Content:
        snapshot = _counts(content.usage_details)
        if content.merge_mode == "replace":
            delta = {
                key: snapshot.get(key, 0) - self._usage.get(key, 0)
                for key in snapshot.keys() | self._usage.keys()
            }
            self._usage = snapshot
            return _with(content, usage_details=UsageDetails(**delta), merge_mode="append")
        for key, value in snapshot.items():
            self._usage[key] = self._usage.get(key, 0) + value
        return content


def _call_key(content: Content) -> str | None:
    """The occurrence key the host groups argument text by."""
    if content.type == "function_call":
        return content.call_id
    if not content.tool_name:
        return None
    return content.call_id or f"{content.server_name or 'default'}::{content.tool_name}"


def _as_text(arguments: object) -> str:
    """Arguments as the JSON string the Responses protocol carries."""
    return arguments if isinstance(arguments, str) else json.dumps(arguments)


def _same_json(left: str, right: str) -> bool:
    try:
        return json.loads(left) == json.loads(right)
    except ValueError:
        return False


def _counts(usage: UsageDetails | None) -> dict[str, int]:
    return {key: value for key, value in (usage or {}).items() if type(value) is int}


def _with(content: Content, **changes: object) -> Content:
    """A shallow copy: the stream keeps the original for the final response."""
    projected = copy.copy(content)
    for name, value in changes.items():
        setattr(projected, name, value)
    return projected
