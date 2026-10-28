"""The platform API's operations over the episode store, independent of the HTTP host.

Cosmos DB is reachable only inside the network, so developers and SMEs read episodes and
attach feedback through this API instead of the database.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from cs_platform.episodes import Feedback, Verdict

if TYPE_CHECKING:
    from cs_platform.episodes import Episode, EpisodeStore

MAX_LIMIT = 100


class EpisodeSummary(BaseModel):
    """One line per episode in listings; ``GET /episodes/{id}`` returns the full episode."""

    id: str
    agent: str
    agent_version: str
    created_at: datetime
    status: str
    input: str
    trace_id: str | None
    tool_calls: int
    verdict: Verdict | None

    @classmethod
    def of(cls, episode: Episode) -> EpisodeSummary:
        return cls(
            id=episode.id,
            agent=episode.agent,
            agent_version=episode.agent_version,
            created_at=episode.created_at,
            status=episode.status,
            input=episode.input,
            trace_id=episode.trace_id,
            tool_calls=len(episode.tool_calls),
            verdict=episode.feedback.verdict if episode.feedback else None,
        )


class FeedbackRequest(BaseModel):
    """An expert's assessment of an episode's outcome."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    actual_root_cause: str | None = Field(
        default=None, description="What the root cause turned out to be, e.g. a failure mode ID."
    )
    note: str | None = None
    reviewer: str | None = None


async def list_episodes(
    store: EpisodeStore, *, agent: str | None = None, limit: int = 20
) -> list[EpisodeSummary]:
    limit = max(1, min(limit, MAX_LIMIT))
    return [EpisodeSummary.of(e) for e in await store.list(agent=agent, limit=limit)]


async def get_episode(store: EpisodeStore, episode_id: str) -> Episode:
    return await store.get(episode_id)


async def add_feedback(store: EpisodeStore, episode_id: str, request: FeedbackRequest) -> Episode:
    feedback = Feedback(**request.model_dump())
    return await store.add_feedback(episode_id, feedback)
