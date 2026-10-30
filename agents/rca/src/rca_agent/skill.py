"""Load the bundled investigation procedure and tag the episodes it produces."""

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict

from cs_platform.episodes import SkillMetadata, fit_to_budget

if TYPE_CHECKING:
    from cs_platform.episodes import Episode, EpisodeStore, Feedback


class _SkillHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class InvestigationSkill:
    """The versioned skill header and its unchanged instruction body."""

    metadata: SkillMetadata
    body: str


def load_investigation_skill() -> InvestigationSkill:
    """Read package data in wheels, or the optimizer's layout in a source checkout."""
    relative = "skills/rca-investigation/SKILL.md"
    bundled = resources.files("rca_agent").joinpath(relative)
    if bundled.is_file():
        document = bundled.read_text(encoding="utf-8")
    else:
        document = (Path(__file__).resolve().parents[2] / relative).read_text(encoding="utf-8")
    opening, front_matter, body = document.split("---", 2)
    if opening.strip():
        raise ValueError("The investigation skill must start with YAML front matter")
    header = _SkillHeader.model_validate(yaml.safe_load(front_matter))
    return InvestigationSkill(
        metadata=SkillMetadata(name=header.name, version=header.metadata["version"]),
        body=body.strip(),
    )


class SkillEpisodeStore:
    """Attach the loaded version at the existing episode-store boundary."""

    def __init__(self, store: EpisodeStore, skill: SkillMetadata) -> None:
        self._store = store
        self._skill = skill

    async def save(self, episode: Episode) -> None:
        episode.skill = self._skill
        fit_to_budget(episode)
        await self._store.save(episode)

    async def get(self, episode_id: str) -> Episode:
        return await self._store.get(episode_id)

    async def list(self, *, agent: str | None = None, limit: int = 20) -> list[Episode]:
        return await self._store.list(agent=agent, limit=limit)

    async def add_feedback(self, episode_id: str, feedback: Feedback) -> Episode:
        return await self._store.add_feedback(episode_id, feedback)
