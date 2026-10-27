"""Builds platform agents from a spec: the one place where capabilities are wired in."""

from typing import TYPE_CHECKING, Any, cast

from agent_framework import Agent

from cs_platform.capture import EpisodeCaptureAgentMiddleware, EpisodeCaptureFunctionMiddleware
from cs_platform.episodes import CosmosEpisodeStore, EpisodeStore, InMemoryEpisodeStore

if TYPE_CHECKING:
    from collections.abc import Sequence

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
) -> Agent[Any]:
    """Create an agent with the platform's cross-cutting capabilities.

    Every agent built here records each run as an episode, including its tool calls and
    structured output. Telemetry comes from Agent Framework's instrumentation layers.
    """
    options = {"response_format": response_format} if response_format else None
    return Agent(
        client,
        spec.instructions,
        name=spec.name,
        description=spec.description,
        tools=list(tools),
        middleware=[EpisodeCaptureAgentMiddleware(spec, store), EpisodeCaptureFunctionMiddleware()],
        default_options=cast("Any", options),
    )


def foundry_client(
    settings: PlatformSettings, credential: AsyncTokenCredential
) -> FoundryChatClient:
    """Chat client for the project's model deployment, authenticated with Entra ID."""
    from agent_framework.foundry import FoundryChatClient

    return FoundryChatClient(
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
