from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from cs_platform.episodes import (
    CosmosEpisodeStore,
    Episode,
    EpisodeNotFoundError,
    EpisodeStore,
    Feedback,
    InMemoryEpisodeStore,
    Verdict,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

T0 = datetime(2026, 10, 20, tzinfo=UTC)


class FakeContainer:
    """Implements the subset of the Cosmos ContainerProxy API the store uses."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.queries: list[tuple[str, list[dict[str, Any]]]] = []

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.items[body["id"]] = body
        return body

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        assert item == partition_key
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return self.items[item]

    def query_items(self, query: str, parameters: list[dict[str, Any]]) -> AsyncIterator[Any]:
        self.queries.append((query, parameters))
        values = {p["name"]: p["value"] for p in parameters}
        rows = [
            i
            for i in self.items.values()
            if "@agent" not in values or i["agent"] == values["@agent"]
        ]
        rows.sort(key=lambda i: i["created_at"], reverse=True)

        async def iterate() -> AsyncIterator[Any]:
            for row in rows[: values["@limit"]]:
                yield row

        return iterate()

    async def patch_item(
        self, item: str, partition_key: str, patch_operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        for operation in patch_operations:
            assert operation["op"] == "set"
            self.items[item][operation["path"].lstrip("/")] = operation["value"]
        return self.items[item]


def _episode(agent: str, minutes: int) -> Episode:
    return Episode(
        agent=agent, agent_version="1", input="x", created_at=T0 + timedelta(minutes=minutes)
    )


@pytest.fixture(params=["memory", "cosmos"])
def store(request: pytest.FixtureRequest) -> EpisodeStore:
    if request.param == "memory":
        return InMemoryEpisodeStore()
    return CosmosEpisodeStore(FakeContainer())  # type: ignore[arg-type]


async def test_save_and_get_round_trip(store: EpisodeStore) -> None:
    episode = _episode("a", 0)
    await store.save(episode)
    assert await store.get(episode.id) == episode


async def test_get_unknown_raises(store: EpisodeStore) -> None:
    with pytest.raises(EpisodeNotFoundError):
        await store.get("missing")


async def test_list_is_newest_first_and_filters_by_agent(store: EpisodeStore) -> None:
    for agent, minutes in [("a", 0), ("b", 1), ("a", 2)]:
        await store.save(_episode(agent, minutes))
    assert [e.created_at for e in await store.list()] == [
        T0 + timedelta(minutes=m) for m in (2, 1, 0)
    ]
    assert {e.agent for e in await store.list(agent="a")} == {"a"}
    assert len(await store.list(limit=1)) == 1


async def test_add_feedback(store: EpisodeStore) -> None:
    episode = _episode("a", 0)
    await store.save(episode)
    feedback = Feedback(verdict=Verdict.INCORRECT, actual_root_cause="FM-05", reviewer="sme")
    updated = await store.add_feedback(episode.id, feedback)
    assert updated.feedback == feedback
    assert (await store.get(episode.id)).feedback == feedback


async def test_feedback_for_unknown_episode_raises(store: EpisodeStore) -> None:
    with pytest.raises(EpisodeNotFoundError):
        await store.add_feedback("missing", Feedback(verdict=Verdict.CORRECT))
