"""Client for the platform API (episodes and feedback).

The API is protected by a function key. Rather than storing it, the CLI fetches it with the
caller's Azure sign-in, so whoever may read the function app's keys in Azure RBAC may use
the API, and nobody else.
"""

import os
from typing import TYPE_CHECKING

import httpx
from azure.identity import DefaultAzureCredential
from pydantic import TypeAdapter

from cs_platform.episodes import Episode
from cs_platform.settings import SettingsError
from platform_api.api import EpisodeSummary

if TYPE_CHECKING:
    from platform_api.api import FeedbackRequest

ARM = "https://management.azure.com"
REQUIRED = (
    "PLATFORM_API_ENDPOINT",
    "PLATFORM_API_FUNCTION_NAME",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
)


class PlatformApiError(RuntimeError):
    pass


def function_key(subscription: str, resource_group: str, app: str) -> str:
    with DefaultAzureCredential() as credential:
        token = credential.get_token(f"{ARM}/.default").token
    response = httpx.post(
        f"{ARM}/subscriptions/{subscription}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Web/sites/{app}/host/default/listkeys",
        params={"api-version": "2024-04-01"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.is_error:
        raise PlatformApiError(f"Can't read the platform API key ({response.status_code})")
    return response.json()["functionKeys"]["default"]


class PlatformClient:
    def __init__(self, endpoint: str, key: str) -> None:
        self._http = httpx.Client(
            base_url=endpoint.rstrip("/") + "/", headers={"x-functions-key": key}, timeout=60
        )

    @classmethod
    def from_env(cls) -> PlatformClient:
        missing = [name for name in REQUIRED if not os.environ.get(name)]
        if missing:
            raise SettingsError(f"{', '.join(missing)} not set; provision the platform first")
        key = function_key(
            os.environ["AZURE_SUBSCRIPTION_ID"],
            os.environ["AZURE_RESOURCE_GROUP"],
            os.environ["PLATFORM_API_FUNCTION_NAME"],
        )
        return cls(os.environ["PLATFORM_API_ENDPOINT"], key)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json_body: str | None = None,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"} if json_body is not None else None
        response = self._http.request(
            method, path, params=params, content=json_body, headers=headers
        )
        if response.is_error:
            raise PlatformApiError(f"{method} {path}: {response.status_code} {response.text}")
        return response

    def list_episodes(self, *, agent: str | None = None, limit: int = 20) -> list[EpisodeSummary]:
        params: dict[str, str | int] = {"limit": limit}
        if agent:
            params["agent"] = agent
        response = self._send("GET", "episodes", params=params)
        return TypeAdapter(list[EpisodeSummary]).validate_json(response.content)

    def get_episode(self, episode_id: str) -> Episode:
        return Episode.model_validate_json(self._send("GET", f"episodes/{episode_id}").content)

    def add_feedback(self, episode_id: str, feedback: FeedbackRequest) -> Episode:
        response = self._send(
            "POST",
            f"episodes/{episode_id}/feedback",
            json_body=feedback.model_dump_json(exclude_none=True),
        )
        return Episode.model_validate_json(response.content)
