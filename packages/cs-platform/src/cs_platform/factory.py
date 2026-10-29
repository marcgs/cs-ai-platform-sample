"""Builds platform agents from a spec: the one place where capabilities are wired in."""

from typing import TYPE_CHECKING, Any, cast

from agent_framework import Agent

from cs_platform.capture import EpisodeCaptureAgentMiddleware, EpisodeCaptureFunctionMiddleware
from cs_platform.episodes import CosmosEpisodeStore, EpisodeStore, InMemoryEpisodeStore
from cs_platform.settings import SettingsError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agent_framework import SupportsChatGetResponse, ToolTypes
    from agent_framework.foundry import FoundryChatClient
    from azure.core.credentials_async import AsyncTokenCredential
    from pydantic import BaseModel

    from cs_platform.settings import PlatformSettings
    from cs_platform.spec import AgentSpec


def build_agent(
    spec: AgentSpec,
    *,
    client: SupportsChatGetResponse[Any],
    store: EpisodeStore,
    tools: Sequence[ToolTypes] = (),
    response_format: type[BaseModel] | None = None,
    options: Mapping[str, Any] | None = None,
) -> Agent[Any]:
    """Create an agent with the platform's cross-cutting capabilities.

    Every agent built here records each run as an episode, including its tool calls and
    structured output. Telemetry comes from Agent Framework's instrumentation layers.
    ``options`` are default chat options for every run (e.g. ``{"store": False}``).
    """
    default_options = dict(options or {})
    if response_format is not None:
        default_options["response_format"] = response_format
    return Agent(
        client,
        spec.instructions,
        name=spec.name,
        description=spec.description,
        tools=list(tools),
        middleware=[EpisodeCaptureAgentMiddleware(spec, store), EpisodeCaptureFunctionMiddleware()],
        default_options=cast("Any", default_options or None),
    )


def foundry_client(
    settings: PlatformSettings, credential: AsyncTokenCredential
) -> FoundryChatClient:
    """Chat client for the project's model deployment, authenticated with Entra ID."""
    from cs_platform.retry import RetryingFoundryChatClient

    return RetryingFoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.model_deployment,
        credential=credential,
    )


def episode_store(settings: PlatformSettings, credential: AsyncTokenCredential) -> EpisodeStore:
    """Cosmos DB when configured, otherwise an in-memory store for local runs."""
    if settings.cosmos_endpoint is None:
        return InMemoryEpisodeStore()
    return CosmosEpisodeStore.connect(
        settings.cosmos_endpoint, settings.cosmos_database, settings.episodes_container, credential
    )


def connect_tools(settings: PlatformSettings, credential: AsyncTokenCredential) -> list[ToolTypes]:
    """The agent's tool source: the Foundry toolbox when configured, else a direct MCP server.

    The toolbox is the platform path (central auth, versioning, one endpoint for all tools).
    A direct MCP URL is for local development against ``func start``. Agent Framework owns
    the MCP connection and opens it on first use.
    """
    if settings.toolbox_endpoint:
        from agent_framework.foundry import FoundryToolbox

        return [FoundryToolbox(credential, url=settings.toolbox_endpoint)]
    if settings.mcp_server_url:
        from agent_framework import MCPStreamableHTTPTool

        return [MCPStreamableHTTPTool("diagnostics", settings.mcp_server_url, load_prompts=False)]
    raise SettingsError("Set TOOLBOX_ENDPOINT or DIAGNOSTICS_MCP_URL to give the agent its tools")
