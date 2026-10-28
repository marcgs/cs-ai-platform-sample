"""Azure Functions entry point for the platform API.

    GET  /api/episodes?agent=rca-agent&limit=20   recent episodes, newest first
    GET  /api/episodes/{id}                       one episode with tool calls and output
    POST /api/episodes/{id}/feedback              attach an expert's verdict

Calls need a function key (``x-functions-key``); `csai` fetches it with the caller's Azure
sign-in, so access follows Azure RBAC on the function app.
"""

import json
import os
from typing import TYPE_CHECKING

import azure.functions as func
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel, ValidationError

from cs_platform.episodes import CosmosEpisodeStore, EpisodeNotFoundError
from platform_api import api

if TYPE_CHECKING:
    from cs_platform.episodes import EpisodeStore

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_store: EpisodeStore | None = None


def store() -> EpisodeStore:
    """The episode store, created once per worker on first use."""
    global _store
    if _store is None:
        _store = CosmosEpisodeStore.connect(
            os.environ["COSMOS_ENDPOINT"],
            os.environ.get("COSMOS_DATABASE", "cs-platform"),
            os.environ.get("COSMOS_EPISODES_CONTAINER", "episodes"),
            DefaultAzureCredential(),
        )
    return _store


def _json(body: BaseModel | list[BaseModel], status: int = 200) -> func.HttpResponse:
    if isinstance(body, list):
        payload = "[" + ",".join(item.model_dump_json() for item in body) + "]"
    else:
        payload = body.model_dump_json()
    return func.HttpResponse(payload, status_code=status, mimetype="application/json")


def _error(message: str, status: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}), status_code=status, mimetype="application/json"
    )


@app.route("episodes", methods=["GET"])
async def list_episodes(req: func.HttpRequest) -> func.HttpResponse:
    try:
        limit = int(req.params.get("limit", "20"))
    except ValueError:
        return _error("limit must be an integer", 400)
    episodes = await api.list_episodes(store(), agent=req.params.get("agent"), limit=limit)
    return _json(list(episodes))


@app.route("episodes/{episode_id}", methods=["GET"])
async def get_episode(req: func.HttpRequest) -> func.HttpResponse:
    episode_id = req.route_params["episode_id"]
    try:
        return _json(await api.get_episode(store(), episode_id))
    except EpisodeNotFoundError:
        return _error(f"episode {episode_id} not found", 404)


@app.route("episodes/{episode_id}/feedback", methods=["POST"])
async def add_feedback(req: func.HttpRequest) -> func.HttpResponse:
    episode_id = req.route_params["episode_id"]
    try:
        request = api.FeedbackRequest.model_validate_json(req.get_body())
    except ValidationError as error:
        return _error(str(error), 400)
    try:
        return _json(await api.add_feedback(store(), episode_id, request))
    except EpisodeNotFoundError:
        return _error(f"episode {episode_id} not found", 404)
