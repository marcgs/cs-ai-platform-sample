"""Assembles the RCA agent from its spec and the platform's building blocks."""

from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cs_platform.factory import build_agent, connect_tools, episode_store, foundry_client
from cs_platform.spec import AgentSpec, load_spec
from rca_agent.report import RcaReport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agent_framework import Agent, SupportsChatGetResponse, ToolTypes
    from azure.core.credentials_async import AsyncTokenCredential

    from cs_platform.episodes import EpisodeStore
    from cs_platform.settings import PlatformSettings


def load_rca_spec() -> AgentSpec:
    return load_spec(Path(str(resources.files("rca_agent").joinpath("agent.spec.yaml"))))


def create_agent(
    settings: PlatformSettings,
    credential: AsyncTokenCredential,
    *,
    client: SupportsChatGetResponse[Any] | None = None,
    store: EpisodeStore | None = None,
    tools: Sequence[ToolTypes] | None = None,
    options: Mapping[str, Any] | None = None,
) -> Agent[Any]:
    """The RCA agent with Azure-backed defaults; pass ``client``/``store``/``tools`` to swap."""
    return build_agent(
        load_rca_spec(),
        client=client or foundry_client(settings, credential),
        store=store or episode_store(settings, credential),
        tools=tools if tools is not None else connect_tools(settings, credential),
        response_format=RcaReport,
        options=options,
    )
