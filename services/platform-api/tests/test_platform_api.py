"""The platform API over an in-memory store: operations and the HTTP layer."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import azure.functions as func
import pytest

from cs_platform.episodes import Episode, InMemoryEpisodeStore, ToolCall, Verdict
from platform_api import api

if TYPE_CHECKING:
    from types import ModuleType

APP_PATH = Path(__file__).parents[1] / "function_app.py"


@pytest.fixture(scope="module")
def app_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("platform_api_function_app", APP_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["platform_api_function_app"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def store() -> InMemoryEpisodeStore:
    store = InMemoryEpisodeStore()
    for i in range(3):
        await store.save(
            Episode(
                id=f"ep-{i}",
                agent="rca-agent" if i < 2 else "other-agent",
                agent_version="0.1.0",
                input=f"M-000{i}: alarm",
                status="succeeded",
                tool_calls=[
                    ToolCall(
                        name="get_logbook",
                        arguments={},
                        started_at=datetime.now(UTC),
                        duration_ms=5.0,
                    )
                ],
            )
        )
    return store


def request(
    method: str, url: str, route: dict[str, str] | None = None, body: object = None
) -> func.HttpRequest:
    return func.HttpRequest(
        method=method,
        url=url,
        params=dict(p.split("=") for p in url.partition("?")[2].split("&") if p),
        route_params=route or {},
        body=json.dumps(body).encode() if body is not None else b"",
    )


async def test_list_filters_by_agent_and_clamps_limit(store: InMemoryEpisodeStore) -> None:
    summaries = await api.list_episodes(store, agent="rca-agent", limit=1000)
    assert {s.id for s in summaries} == {"ep-0", "ep-1"}
    assert all(s.tool_calls == 1 and s.verdict is None for s in summaries)


async def test_feedback_is_stored_on_the_episode(store: InMemoryEpisodeStore) -> None:
    request_ = api.FeedbackRequest(verdict=Verdict.INCORRECT, actual_root_cause="FM-05")
    episode = await api.add_feedback(store, "ep-0", request_)
    assert episode.feedback is not None
    assert episode.feedback.actual_root_cause == "FM-05"
    assert (await api.list_episodes(store, agent="rca-agent"))[-1].verdict is not None


async def test_http_routes(
    app_module: ModuleType, store: InMemoryEpisodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_store", store)

    listed = await app_module.list_episodes(request("GET", "/api/episodes?agent=rca-agent&limit=5"))
    assert listed.status_code == 200
    assert len(json.loads(listed.get_body())) == 2

    shown = await app_module.get_episode(
        request("GET", "/api/episodes/ep-1", {"episode_id": "ep-1"})
    )
    assert json.loads(shown.get_body())["input"] == "M-0001: alarm"

    missing = await app_module.get_episode(
        request("GET", "/api/episodes/nope", {"episode_id": "nope"})
    )
    assert missing.status_code == 404

    added = await app_module.add_feedback(
        request(
            "POST",
            "/api/episodes/ep-1/feedback",
            {"episode_id": "ep-1"},
            {"verdict": "correct", "note": "matches"},
        )
    )
    assert added.status_code == 200
    assert json.loads(added.get_body())["feedback"]["verdict"] == "correct"

    invalid = await app_module.add_feedback(
        request("POST", "/api/episodes/ep-1/feedback", {"episode_id": "ep-1"}, {"verdict": "maybe"})
    )
    assert invalid.status_code == 400

    bad_limit = await app_module.list_episodes(request("GET", "/api/episodes?limit=lots"))
    assert bad_limit.status_code == 400


def test_routes_are_registered(app_module: ModuleType) -> None:
    names = {f.get_function_name() for f in app_module.app.get_functions()}
    assert names == {"list_episodes", "get_episode", "add_feedback"}
