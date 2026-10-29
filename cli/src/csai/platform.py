"""Client for the platform API (episodes and feedback).

The API is protected by a function key. Rather than storing it, the CLI fetches it with the
caller's Azure sign-in, so whoever may read the function app's keys in Azure RBAC may use
the API, and nobody else.
"""

import os
import time
from typing import TYPE_CHECKING

import httpx
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

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
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PlatformEpisodeNotFoundError(PlatformApiError):
    """The API confirmed that this exact episode is not stored."""


class _FunctionKeys(BaseModel):
    default: str = Field(min_length=1)


class _FunctionKeyResponse(BaseModel):
    function_keys: _FunctionKeys = Field(alias="functionKeys")


def function_key(subscription: str, resource_group: str, app: str) -> str:
    try:
        with DefaultAzureCredential() as credential:
            token = credential.get_token(f"{ARM}/.default").token
    except AzureError as error:
        raise PlatformApiError(
            f"Can't acquire the platform API credential ({type(error).__name__})"
        ) from error
    try:
        response = _request_function_key(subscription, resource_group, app, token)
    except httpx.HTTPError as error:
        raise PlatformApiError(
            f"Can't read the platform API key ({type(error).__name__})"
        ) from error
    if response.is_error:
        raise PlatformApiError(
            f"Can't read the platform API key ({response.status_code})",
            status_code=response.status_code,
        )
    try:
        return _FunctionKeyResponse.model_validate_json(response.content).function_keys.default
    except ValidationError as error:
        raise PlatformApiError("Invalid platform API key response") from error


def _request_function_key(
    subscription: str, resource_group: str, app: str, token: str
) -> httpx.Response:
    response = httpx.post(
        f"{ARM}/subscriptions/{subscription}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Web/sites/{app}/host/default/listkeys",
        params={"api-version": "2024-04-01"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    return response


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
        missing_episode_id: str | None = None,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"} if json_body is not None else None
        try:
            response = self._http.request(
                method, path, params=params, content=json_body, headers=headers
            )
        except httpx.HTTPError as error:
            raise PlatformApiError(f"{method} {path}: {type(error).__name__}") from error
        if response.is_error:
            if response.status_code == 404 and missing_episode_id is not None:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if payload == {"error": f"episode {missing_episode_id} not found"}:
                    raise PlatformEpisodeNotFoundError(
                        f"Episode {missing_episode_id} not found", status_code=404
                    )
            raise PlatformApiError(
                f"{method} {path}: {response.status_code} {response.text}",
                status_code=response.status_code,
            )
        return response

    def list_episodes(self, *, agent: str | None = None, limit: int = 20) -> list[EpisodeSummary]:
        params: dict[str, str | int] = {"limit": limit}
        if agent:
            params["agent"] = agent
        response = self._send("GET", "episodes", params=params)
        return TypeAdapter(list[EpisodeSummary]).validate_json(response.content)

    def get_episode(self, episode_id: str) -> Episode:
        response = self._send("GET", f"episodes/{episode_id}", missing_episode_id=episode_id)
        try:
            return Episode.model_validate_json(response.content)
        except ValidationError as error:
            raise PlatformApiError("Invalid episode response") from error

    def wait_for_episode(
        self, episode_id: str, response_id: str, *, attempts: int = 5, interval_s: float = 0.5
    ) -> Episode | None:
        """Bounded point reads, retrying only the API's exact episode-not-found reply."""
        if attempts < 1 or interval_s < 0:
            raise ValueError("Polling requires positive attempts and a nonnegative interval")
        for attempt in range(attempts):
            try:
                episode = self.get_episode(episode_id)
            except PlatformEpisodeNotFoundError:
                pass
            else:
                if episode.id != episode_id or episode.hosted_response_id != response_id:
                    raise PlatformApiError("Episode identity does not match the hosted response")
                return episode
            if attempt + 1 < attempts:
                time.sleep(interval_s)
        return None

    def add_feedback(self, episode_id: str, feedback: FeedbackRequest) -> Episode:
        response = self._send(
            "POST",
            f"episodes/{episode_id}/feedback",
            json_body=feedback.model_dump_json(exclude_none=True),
        )
        return Episode.model_validate_json(response.content)
