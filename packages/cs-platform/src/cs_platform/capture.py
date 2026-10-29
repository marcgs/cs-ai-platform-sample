"""Episode capture: platform middleware that records every agent run.

The agent middleware opens an episode per run and hands a recorder to the tool layer through
the run's function-invocation kwargs. This works for streaming runs too, where tools execute
after the agent middleware has returned. The function middleware records each tool call and
strips the recorder before the tool runs, so it never reaches tool arguments.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from agent_framework import AgentMiddleware, AgentResponse, FunctionMiddleware, ResponseStream
from opentelemetry import trace
from pydantic import BaseModel

from cs_platform.episodes import Episode, ToolCall, Usage, fit_to_budget
from cs_platform.hosting import HOSTED_RESPONSE_ID_OPTION, hosted_episode_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent_framework import AgentContext, FunctionInvocationContext, Message

    from cs_platform.episodes import EpisodeStore
    from cs_platform.spec import AgentSpec

logger = logging.getLogger(__name__)

RECORDER_KEY = "cs_platform_episode_recorder"
EPISODE_ID_KEY = "episode_id"


class EpisodeRecorder:
    """Collects one run's tool calls and outcome, then saves the episode once."""

    def __init__(self, episode: Episode, store: EpisodeStore, span: trace.Span) -> None:
        self.episode = episode
        self._store = store
        self.span = span

    def add_tool_call(self, call: ToolCall) -> None:
        self.episode.tool_calls.append(call)

    async def finish(
        self, response: AgentResponse[Any] | None, error: BaseException | None
    ) -> None:
        if self.episode.status != "running":
            return
        episode = self.episode
        episode.completed_at = datetime.now(UTC)
        if response is not None:
            episode.output_text = response.text
            episode.usage = _usage(response)
            try:
                value = response.value
            except Exception as exc:  # structured output failed validation
                error = error or exc
                value = None
            if isinstance(value, BaseModel):
                episode.output = value.model_dump(mode="json")
        if error is not None:
            episode.status = "failed"
            episode.error = f"{type(error).__name__}: {error}"
        else:
            episode.status = "succeeded"
        if error is not None:
            self.span.record_exception(error)
            self.span.set_status(trace.StatusCode.ERROR, str(error))
        # Tool results are evidence, so they're kept whole unless the episode wouldn't fit.
        fit_to_budget(episode)
        try:
            await self._store.save(episode)
        except Exception:
            # Losing an episode must not fail the user's request; it's visible in the logs.
            logger.exception("Could not save episode %s", episode.id)


class EpisodeCaptureAgentMiddleware(AgentMiddleware):
    def __init__(self, spec: AgentSpec, store: EpisodeStore) -> None:
        self._spec = spec
        self._store = store

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        span = trace.get_tracer(__name__).start_span("cs_platform.episode")
        # Middleware precedes the framework's agent span. Keep this parent alive across
        # lazy stream consumption, without leaving context attached between iterator pulls.
        try:
            with trace.use_span(span, end_on_exit=False, record_exception=False):
                await self._process(context, call_next, span)
        except BaseException:
            span.end()
            raise

    async def _process(
        self,
        context: AgentContext,
        call_next: Callable[[], Awaitable[None]],
        span: trace.Span,
    ) -> None:
        options = dict(context.options or {})
        response_id = options.pop(HOSTED_RESPONSE_ID_OPTION, None)
        context.options = options
        episode = Episode(
            agent=self._spec.name,
            agent_version=self._spec.version,
            input=_input_text(context.messages),
            trace_id=_current_trace_id(),
        )
        if isinstance(response_id, str):
            episode.id = hosted_episode_id(response_id)
            episode.hosted_response_id = response_id
        trace.get_current_span().set_attribute("cs_platform.episode_id", episode.id)
        recorder = EpisodeRecorder(episode, self._store, span)
        context.function_invocation_kwargs = {
            **(context.function_invocation_kwargs or {}),
            RECORDER_KEY: recorder,
        }

        try:
            await call_next()
        except Exception as error:  # cancellation propagates without a store round-trip
            await recorder.finish(None, error)
            raise

        if context.stream:
            if isinstance(context.result, ResponseStream):
                context.result.with_pull_context_manager(
                    lambda: trace.use_span(span, end_on_exit=False, record_exception=False)
                )

            async def on_result(response: AgentResponse[Any]) -> AgentResponse[Any]:
                await recorder.finish(response, None)
                response.additional_properties[EPISODE_ID_KEY] = episode.id
                return response

            async def on_cleanup() -> None:
                try:
                    await recorder.finish(
                        None,
                        sys.exception() or RuntimeError("stream ended without a final response"),
                    )
                finally:
                    span.end()

            context.stream_result_hooks.append(on_result)
            context.stream_cleanup_hooks.append(on_cleanup)
            return

        result = context.result
        response = result if isinstance(result, AgentResponse) else None
        await recorder.finish(response, None)
        if response is not None:
            response.additional_properties[EPISODE_ID_KEY] = episode.id
        span.end()


class EpisodeCaptureFunctionMiddleware(FunctionMiddleware):
    async def process(
        self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        recorder = context.kwargs.get(RECORDER_KEY)
        if not isinstance(recorder, EpisodeRecorder):
            await call_next()
            return
        context.kwargs = {k: v for k, v in context.kwargs.items() if k != RECORDER_KEY}

        started_at = datetime.now(UTC)
        start = perf_counter()
        error: str | None = None
        result: str | None = None
        try:
            await call_next()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        else:
            result = _result_text(context.result)
        finally:
            recorder.add_tool_call(
                ToolCall(
                    name=context.function.name,
                    arguments=_arguments(context.arguments),
                    result=result,
                    error=error,
                    started_at=started_at,
                    duration_ms=round((perf_counter() - start) * 1000, 2),
                )
            )


def _input_text(messages: list[Message]) -> str:
    return "\n".join(m.text for m in messages if m.role == "user" and m.text)


def _current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.trace_id:032x}" if span_context.is_valid else None


def _arguments(arguments: BaseModel | Any) -> dict[str, Any]:
    if isinstance(arguments, BaseModel):
        return arguments.model_dump(mode="json")
    return dict(arguments)


def _result_text(result: object) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "\n".join(str(getattr(item, "text", None) or item) for item in result)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    else:
        text = json.dumps(result, default=str)
    return text


def _usage(response: AgentResponse) -> Usage | None:
    details = response.usage_details
    if not details:
        return None
    return Usage(
        input_tokens=details.get("input_token_count"),
        output_tokens=details.get("output_token_count"),
    )
