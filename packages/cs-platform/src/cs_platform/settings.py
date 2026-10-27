"""Platform settings, read from environment variables.

Infrastructure outputs (``azd env``) and local ``.env`` files provide these values. Only the
Foundry project endpoint is mandatory; everything else enables optional capabilities.
"""

import os
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping


class SettingsError(ValueError):
    """A required setting is missing."""


class PlatformSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    foundry_project_endpoint: str
    model_deployment: str = "gpt-5.4-mini"
    toolbox_endpoint: str | None = None
    """Foundry toolbox MCP endpoint; preferred over a direct MCP server URL."""
    mcp_server_url: str | None = None
    """Direct MCP server URL, e.g. the local Functions host during development."""
    cosmos_endpoint: str | None = None
    cosmos_database: str = "cs-platform"
    episodes_container: str = "episodes"
    applicationinsights_connection_string: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> PlatformSettings:
        env = os.environ if environ is None else environ
        endpoint = env.get("FOUNDRY_PROJECT_ENDPOINT")
        if not endpoint:
            raise SettingsError("FOUNDRY_PROJECT_ENDPOINT is not set")
        optional = {
            "model_deployment": env.get("FOUNDRY_MODEL_DEPLOYMENT_NAME"),
            "toolbox_endpoint": env.get("TOOLBOX_ENDPOINT"),
            "mcp_server_url": env.get("DIAGNOSTICS_MCP_URL"),
            "cosmos_endpoint": env.get("COSMOS_ENDPOINT"),
            "cosmos_database": env.get("COSMOS_DATABASE"),
            "episodes_container": env.get("COSMOS_EPISODES_CONTAINER"),
            "applicationinsights_connection_string": env.get(
                "APPLICATIONINSIGHTS_CONNECTION_STRING"
            ),
        }
        return cls(
            foundry_project_endpoint=endpoint,
            **{key: value for key, value in optional.items() if value},
        )
