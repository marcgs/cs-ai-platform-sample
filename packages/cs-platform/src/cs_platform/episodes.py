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
    feedback: Feedback | None = None


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
