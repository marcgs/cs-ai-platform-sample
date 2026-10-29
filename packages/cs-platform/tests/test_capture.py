from typing import TYPE_CHECKING

import pytest
from agent_framework import tool
from pydantic import BaseModel

from cs_platform.capture import EPISODE_ID_KEY
from cs_platform.episodes import EPISODE_MAX_BYTES, Episode, InMemoryEpisodeStore
from cs_platform.factory import build_agent
from cs_platform.testing import ScriptedChatClient, call, text

if TYPE_CHECKING:
    from cs_platform.spec import AgentSpec


class Report(BaseModel):
    summary: str
    confidence: float


@tool
def get_status(machine_id: str) -> str:
    """Return the status of a machine."""
    return f"{machine_id}: stage temperature 22.4 degC (tolerance 22.0 +/- 0.15)"


@tool
def broken_tool(machine_id: str) -> str:
    """A tool that always fails."""
    raise RuntimeError(f"backend unavailable for {machine_id}")


REPORT_JSON = '{"summary": "Stage cooling drift", "confidence": 0.8}'


async def _only_episode(store: InMemoryEpisodeStore) -> Episode:
    episodes = await store.list()
    assert len(episodes) == 1
    return episodes[0]


@pytest.mark.parametrize("stream", [False, True])
async def test_run_is_recorded_as_episode(spec: AgentSpec, stream: bool) -> None:
    store = InMemoryEpisodeStore()
    client = ScriptedChatClient(
        [[call("get_status", machine_id="M-0001")], [text(REPORT_JSON)]],
        usage={"input_token_count": 120, "output_token_count": 30},
    )
    agent = build_agent(
        spec, client=client, store=store, tools=[get_status], response_format=Report
    )

    if stream:
        response = await agent.run("M-0001 overlay drift", stream=True).get_final_response()
    else:
        response = await agent.run("M-0001 overlay drift")

    episode = await _only_episode(store)
    assert response.additional_properties[EPISODE_ID_KEY] == episode.id
    assert episode.status == "succeeded"
    assert episode.agent == "test-agent"
    assert episode.agent_version == "1.2.3"
    assert episode.input == "M-0001 overlay drift"
    assert episode.output == {"summary": "Stage cooling drift", "confidence": 0.8}
    assert episode.completed_at is not None
    [tool_call] = episode.tool_calls
    assert tool_call.name == "get_status"
    assert tool_call.arguments == {"machine_id": "M-0001"}
    assert tool_call.result is not None
    assert "22.4" in tool_call.result
    assert tool_call.error is None
    assert episode.usage is not None
    assert episode.usage.input_tokens == 120


async def test_tool_results_reach_the_model_unchanged(spec: AgentSpec) -> None:
    client = ScriptedChatClient([[call("get_status", machine_id="M-0002")], [text("done")]])
    agent = build_agent(spec, client=client, store=InMemoryEpisodeStore(), tools=[get_status])
    await agent.run("check M-0002")
    second_request = " ".join(str(c.to_dict()) for m in client.requests[1] for c in m.contents)
    assert "M-0002: stage temperature" in second_request


@tool
def get_history(machine_id: str) -> str:
    """Return a long event history, with the evidence ref at the end."""
    return "x" * 10_000 + f" EV-999999 {machine_id}"


@tool
def get_huge_dump(machine_id: str) -> str:
    """Return more than an episode can hold."""
    return "y" * 2_000_000


async def test_long_tool_results_are_kept_whole(spec: AgentSpec) -> None:
    store = InMemoryEpisodeStore()
    client = ScriptedChatClient([[call("get_history", machine_id="M-0004")], [text("done")]])
    agent = build_agent(spec, client=client, store=store, tools=[get_history])
    await agent.run("check M-0004")

    [tool_call] = (await _only_episode(store)).tool_calls
    assert tool_call.result is not None
    assert tool_call.result.endswith("EV-999999 M-0004")
    assert not tool_call.result_truncated


async def test_oversized_episode_is_cut_to_fit_and_flagged(spec: AgentSpec) -> None:
    store = InMemoryEpisodeStore()
    client = ScriptedChatClient([[call("get_huge_dump", machine_id="M-0004")], [text("done")]])
    agent = build_agent(spec, client=client, store=store, tools=[get_huge_dump])
    await agent.run("check M-0004")

    episode = await _only_episode(store)
    assert episode.truncated
    assert episode.tool_calls[0].result_truncated
    assert len(episode.model_dump_json().encode()) <= EPISODE_MAX_BYTES


async def test_tool_failure_is_recorded(spec: AgentSpec) -> None:
    store = InMemoryEpisodeStore()
    client = ScriptedChatClient([[call("broken_tool", machine_id="M-0003")], [text("sorry")]])
    agent = build_agent(spec, client=client, store=store, tools=[broken_tool])
    await agent.run("check M-0003")

    [tool_call] = (await _only_episode(store)).tool_calls
    assert tool_call.error is not None
    assert "backend unavailable" in tool_call.error
    assert tool_call.result is None


async def test_model_failure_marks_episode_failed(spec: AgentSpec) -> None:
    store = InMemoryEpisodeStore()
    agent = build_agent(spec, client=ScriptedChatClient([]), store=store)
    with pytest.raises(IndexError):
        await agent.run("anything")

    episode = await _only_episode(store)
    assert episode.status == "failed"
    assert episode.error is not None
    assert "IndexError" in episode.error


async def test_invalid_structured_output_marks_episode_failed(spec: AgentSpec) -> None:
    store = InMemoryEpisodeStore()
    client = ScriptedChatClient([[text("not json at all")]])
    agent = build_agent(spec, client=client, store=store, response_format=Report)
    await agent.run("anything")

    episode = await _only_episode(store)
    assert episode.status == "failed"
    assert episode.output is None
    assert episode.output_text == "not json at all"


async def test_store_failure_does_not_fail_the_run(spec: AgentSpec) -> None:
    class BrokenStore(InMemoryEpisodeStore):
        async def save(self, episode: Episode) -> None:
            raise ConnectionError("store down")

    agent = build_agent(spec, client=ScriptedChatClient([[text("ok")]]), store=BrokenStore())
    response = await agent.run("anything")
    assert response.text == "ok"


async def test_each_run_gets_its_own_episode(spec: AgentSpec) -> None:
    store = InMemoryEpisodeStore()
    client = ScriptedChatClient([[call("get_status", machine_id="M-1")], [text("a")], [text("b")]])
    agent = build_agent(spec, client=client, store=store, tools=[get_status])
    await agent.run("first")
    await agent.run("second")

    episodes = {e.input: e for e in await store.list()}
    assert len(episodes["first"].tool_calls) == 1
    assert episodes["second"].tool_calls == []
