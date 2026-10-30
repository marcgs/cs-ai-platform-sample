"""Assembles the RCA agent from its spec and the platform's building blocks."""

from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cs_platform.factory import build_agent, connect_tools, episode_store, foundry_client
from cs_platform.spec import AgentSpec, load_spec
from rca_agent.report import RcaReport
from rca_agent.skill import SkillEpisodeStore, load_investigation_skill

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agent_framework import Agent, SupportsChatGetResponse, ToolTypes
    from azure.core.credentials_async import AsyncTokenCredential

    from cs_platform.episodes import EpisodeStore
    from cs_platform.settings import PlatformSettings
    from rca_agent.skill import InvestigationSkill


def _spec_with_skill(skill: InvestigationSkill) -> AgentSpec:
    spec = load_spec(Path(str(resources.files("rca_agent").joinpath("agent.spec.yaml"))))
    return spec.model_copy(update={"instructions": f"{spec.instructions}\n\n{skill.body}"})


def load_rca_spec() -> AgentSpec:
    """Resolve the role and bundle the investigation procedure once into its context."""
    return _spec_with_skill(load_investigation_skill())


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
    skill = load_investigation_skill()
    return build_agent(
        _spec_with_skill(skill),
        client=client or foundry_client(settings, credential),
        store=SkillEpisodeStore(store or episode_store(settings, credential), skill.metadata),
        tools=tools if tools is not None else connect_tools(settings, credential),
        response_format=RcaReport,
        options=options,
    )
