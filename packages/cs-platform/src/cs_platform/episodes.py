"""Episodes: the structured record of one agent run, plus expert feedback.

Episodes are the inner learning loop. They're written by the platform (not the LLM), so the
record of what the agent saw and concluded is complete and trustworthy.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from azure.core.credentials_async import AsyncTokenCredential
    from azure.cosmos.aio import ContainerProxy


def _now() -> datetime:
    return datetime.now(UTC)


class Verdict(StrEnum):
    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"


class Feedback(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: Verdict
    actual_root_cause: str | None = None
    note: str | None = None
    reviewer: str | None = None
    submitted_at: datetime = Field(default_factory=_now)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: str | None = None
    result_truncated: bool = False
    error: str | None = None
    started_at: datetime
    duration_ms: float


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class Episode(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source: Literal["real", "synthetic"] = "real"
    """Run provenance, not whether the incident's domain data happens to be fictional."""
    agent: str
    agent_version: str
    created_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    status: Literal["running", "succeeded", "failed"] = "running"
    input: str
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    output: dict[str, Any] | None = None
    """The structured result, when the agent has a response format."""
    output_text: str | None = None
    error: str | None = None
    usage: Usage | None = None
    trace_id: str | None = None
    hosted_response_id: str | None = None
    """Host-issued Responses ID; absent on local runs and legacy records."""
    feedback: Feedback | None = None
    truncated: list[str] = Field(default_factory=list[str])
    """The parts cut to fit the store, in the order they were cut (see ``fit_to_budget``)."""


# Cosmos DB rejects items over 2 MB; leave room for system properties and feedback added later.
EPISODE_MAX_BYTES = 1_500_000
MAX_ERROR_CHARS = 1_000


def _json_size(episode: Episode) -> int:
    return len(episode.model_dump_json().encode())


def _cut(text: str, excess: int) -> str:
    # Every character is at least one byte of JSON, so this frees at least `excess` bytes.
    return text[: max(0, len(text) - excess)]


def fit_to_budget(episode: Episode, max_bytes: int = EPISODE_MAX_BYTES) -> None:
    """Shrink an episode in place until its JSON fits ``max_bytes``.

    Parts are cut in order of how little the record loses, re-measuring after each step: tool
    results (largest first, each flagged with ``result_truncated``), the output text, tool
    arguments, error messages, the input, the structured output, and finally the tool calls
    themselves. After that only fixed metadata is left, so any budget of a few kilobytes holds.
    ``episode.truncated`` lists what was cut.
    """

    def excess() -> int:
        return _json_size(episode) - max_bytes

    def mark(part: str) -> None:
        # Flags add bytes too, so they're set before the cut is measured.
        if part not in episode.truncated:
            episode.truncated.append(part)

    while excess() > 0 and (calls := [c for c in episode.tool_calls if c.result]):
        largest = max(calls, key=lambda c: len(c.result or ""))
        largest.result_truncated = True
        mark("tool_calls.result")
        largest.result = _cut(largest.result or "", max(0, excess()))
    if excess() > 0 and episode.output_text:
        mark("output_text")
        episode.output_text = _cut(episode.output_text, max(0, excess()))
    if excess() > 0 and any(c.arguments for c in episode.tool_calls):
        for c in episode.tool_calls:
            c.arguments = {}
        mark("tool_calls.arguments")
    if excess() > 0:
        for c in episode.tool_calls:
            if c.error and len(c.error) > MAX_ERROR_CHARS:
                c.error = c.error[:MAX_ERROR_CHARS]
                mark("tool_calls.error")
        if episode.error and len(episode.error) > MAX_ERROR_CHARS:
            episode.error = episode.error[:MAX_ERROR_CHARS]
            mark("error")
    if excess() > 0 and episode.input:
        mark("input")
        episode.input = _cut(episode.input, max(0, excess()))
    if excess() > 0 and episode.output is not None:
        episode.output = None
        mark("output")
    if excess() > 0 and episode.tool_calls:
        episode.tool_calls = []
        mark("tool_calls")


class EpisodeNotFoundError(LookupError):
    def __init__(self, episode_id: str) -> None:
        super().__init__(f"Unknown episode: {episode_id}")


class EpisodeStore(Protocol):
    async def save(self, episode: Episode) -> None: ...

    async def get(self, episode_id: str) -> Episode: ...

    async def list(self, *, agent: str | None = None, limit: int = 20) -> list[Episode]: ...

    async def add_feedback(self, episode_id: str, feedback: Feedback) -> Episode: ...


class InMemoryEpisodeStore:
    """For tests and local runs without Cosmos DB."""

    def __init__(self) -> None:
        self._episodes: dict[str, Episode] = {}

    async def save(self, episode: Episode) -> None:
        self._episodes[episode.id] = episode.model_copy(deep=True)

    async def get(self, episode_id: str) -> Episode:
        try:
            return self._episodes[episode_id].model_copy(deep=True)
        except KeyError:
            raise EpisodeNotFoundError(episode_id) from None

    async def list(self, *, agent: str | None = None, limit: int = 20) -> list[Episode]:
        matching = [e for e in self._episodes.values() if agent is None or e.agent == agent]
        matching.sort(key=lambda e: e.created_at, reverse=True)
        return [e.model_copy(deep=True) for e in matching[:limit]]

    async def add_feedback(self, episode_id: str, feedback: Feedback) -> Episode:
        episode = await self.get(episode_id)
        updated = episode.model_copy(update={"feedback": feedback})
        await self.save(updated)
        return updated


class CosmosEpisodeStore:
    """Episodes in Azure Cosmos DB (NoSQL), partitioned by episode id, Entra auth only."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def connect(
        cls, endpoint: str, database: str, container: str, credential: AsyncTokenCredential
    ) -> CosmosEpisodeStore:
        from azure.cosmos.aio import CosmosClient

        client = CosmosClient(endpoint, credential=credential)
        return cls(client.get_database_client(database).get_container_client(container))

    async def save(self, episode: Episode) -> None:
        await self._container.upsert_item(episode.model_dump(mode="json"))

    async def get(self, episode_id: str) -> Episode:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            item = await self._container.read_item(episode_id, partition_key=episode_id)
        except CosmosResourceNotFoundError:
            raise EpisodeNotFoundError(episode_id) from None
        return Episode.model_validate(item)

    async def list(self, *, agent: str | None = None, limit: int = 20) -> list[Episode]:
        query = "SELECT TOP @limit * FROM e"
        parameters: list[dict[str, Any]] = [{"name": "@limit", "value": limit}]
        if agent is not None:
            query += " WHERE e.agent = @agent"
            parameters.append({"name": "@agent", "value": agent})
        query += " ORDER BY e.created_at DESC"
        items = self._container.query_items(query, parameters=parameters)
        return [Episode.model_validate(item) async for item in items]

    async def add_feedback(self, episode_id: str, feedback: Feedback) -> Episode:
        await self.get(episode_id)
        item = await self._container.patch_item(
            episode_id,
            partition_key=episode_id,
            patch_operations=[
                {"op": "set", "path": "/feedback", "value": feedback.model_dump(mode="json")}
            ],
        )
        return Episode.model_validate(item)
