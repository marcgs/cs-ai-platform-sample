"""Bounded rate-limit recovery for a single model turn, never the tool loop."""

import asyncio
import logging
import math
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, cast

from agent_framework import ChatResponse, ChatResponseUpdate, Message, ResponseStream
from agent_framework.foundry import FoundryChatClient
from openai import RateLimitError
from opentelemetry import trace

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)


def _rate_limit(error: Exception) -> RateLimitError | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RateLimitError):
            return current
        current = current.__cause__
    return None


def _server_delay(error: RateLimitError) -> float | None:
    headers = error.response.headers
    for name in ("retry-after-ms", "x-ms-retry-after-ms", "retry-after"):
        value = headers.get(name)
        if value is None:
            continue
        try:
            delay = float(value) / (1000 if name.endswith("-ms") else 1)
        except ValueError:
            if name != "retry-after":
                continue
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                delay = (date - datetime.now(UTC)).total_seconds()
            except ValueError, TypeError, OverflowError:
                continue
        if math.isfinite(delay):
            return max(0.0, delay)
    return None


class ModelRetryPolicy:
    """At most four attempts and 120 seconds of waiting per model turn.

    Server delays are never shortened: a delay beyond the remaining budget terminates
    the turn. Cancellation is not intercepted. No request or error payload is logged.
    """

    def __init__(self, *, max_attempts: int = 4, max_wait: float = 120.0) -> None:
        if max_attempts < 1 or not math.isfinite(max_wait) or max_wait < 0:
            raise ValueError("Retry limits must be finite and non-negative, with an attempt")
        self.max_attempts = max_attempts
        self.max_wait = max_wait

    async def _wait(
        self, error: Exception, attempt: int, waited: float, *, emitted: bool = False
    ) -> float:
        limited = _rate_limit(error)
        if limited is None:
            raise error
        delay = _server_delay(limited)
        if delay is None:
            delay = random.uniform(0.5, 1.0) * 2 ** min(attempt - 1, 3)
        retry = (
            not emitted
            and attempt < self.max_attempts
            and delay <= self.max_wait - waited
            and limited.response.headers.get("x-should-retry", "").lower() != "false"
        )
        attributes = {
            "retry.attempt": attempt,
            "retry.delay_seconds": delay,
            "retry.will_retry": retry,
            "retry.stream_emitted": emitted,
            "http.response.status_code": 429,
        }
        logger.warning(
            "Model rate limit: attempt=%s retry=%s delay_seconds=%s stream_emitted=%s",
            attempt,
            retry,
            delay,
            emitted,
            extra=attributes,
        )
        trace.get_current_span().add_event("cs_platform.model.rate_limit", attributes)
        if not retry:
            raise error
        await asyncio.sleep(delay)
        return waited + delay

    async def response[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Retry one non-streaming model request on 429 only."""
        waited = 0.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await operation()
            except Exception as error:
                waited = await self._wait(error, attempt, waited)
        raise AssertionError("unreachable")

    def stream(
        self, operation: Callable[[], ResponseStream[ChatResponseUpdate, ChatResponse[Any]]]
    ) -> ResponseStream[ChatResponseUpdate, ChatResponse[Any]]:
        """Retry only before the first update, including empty/metadata updates."""
        current: ResponseStream[ChatResponseUpdate, ChatResponse[Any]] | None = None

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            nonlocal current
            waited = 0.0
            emitted = False
            for attempt in range(1, self.max_attempts + 1):
                try:
                    current = operation()
                    async for update in current:
                        emitted = True
                        yield update
                    return
                except Exception as error:
                    waited = await self._wait(error, attempt, waited, emitted=emitted)

        async def finalize(_: Sequence[ChatResponseUpdate]) -> ChatResponse[Any]:
            assert current is not None
            return await current.get_final_response()

        async def cleanup() -> None:
            if current is not None:
                await current.close()

        return ResponseStream(updates(), finalizer=finalize, cleanup_hooks=[cleanup])


class RetryingFoundryChatClient(FoundryChatClient):
    """Foundry client with retry below function invocation and SDK retries disabled."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.client.max_retries = 0
        self._model_retry = ModelRetryPolicy()

    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        options: Mapping[str, Any],
        stream: bool = False,
        **kwargs: Any,
    ) -> Awaitable[ChatResponse[Any]] | ResponseStream[ChatResponseUpdate, ChatResponse[Any]]:
        inner = super()._inner_get_response
        if stream:

            def start() -> ResponseStream[ChatResponseUpdate, ChatResponse[Any]]:
                result = inner(messages=messages, options=options, stream=True, **kwargs)
                assert isinstance(result, ResponseStream)
                return cast("ResponseStream[ChatResponseUpdate, ChatResponse[Any]]", result)

            return self._model_retry.stream(start)

        async def request() -> ChatResponse[Any]:
            result = inner(messages=messages, options=options, stream=False, **kwargs)
            assert not isinstance(result, ResponseStream)
            return await result

        return self._model_retry.response(request)
