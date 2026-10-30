"""Portable L2/L3 interchange contracts; reviewer assertions are not ground truth."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cs_platform.episodes import Feedback, Verdict

type Classification = Literal[
    "missed_evidence", "wrong_ranking", "knowledge_gap", "data_quality", "instruction_followed"
]
type Route = Literal["learner", "knowledge", "backlog"]


class Review(BaseModel):
    """One review of one episode; several reviewers and duplicate rows are allowed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    episode_id: str
    source: Literal["synthetic", "real"]
    feedback: Feedback


class EpisodeTruth(BaseModel):
    """Generator-only truth, kept out of the analysis input and the agent's transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: str
    pattern_id: str | None
    expected_failure_mode: str
    actual_failure_mode: str = Field(description="The agent's actual top-ranked output, not truth.")
    verdict: Verdict
    machine_id: str
    platform: str
    software_release: str
    downtime_hours: float = Field(ge=0)


class PlantedPattern(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    description: str
    classification: Classification
    route: Route
    episode_ids: list[str]


class AnswerKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["synthetic"] = "synthetic"
    seed: int
    patterns: list[PlantedPattern]
    episodes: list[EpisodeTruth]
