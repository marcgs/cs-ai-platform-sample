"""Analysis contracts deliberately have no dependency on generator truth."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cs_platform.episodes import Episode

type Category = Literal[
    "missed_evidence",
    "wrong_ranking",
    "knowledge_gap",
    "data_quality",
    "tool_error",
    "ambiguous_input",
    "instruction_followed",
]
type Route = Literal["learner_brief", "knowledge_proposal", "backlog"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Label(Record):
    """Fixed category plus a distinguishing, reusable evidence/condition signature."""

    category: Category
    condition: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1000)


class ReviewerAgreement(Record):
    comparisons: int
    agreements: int
    reliability: float


class ReviewSummary(Record):
    episode_id: str
    verdict: Literal["correct", "partially_correct", "incorrect"] | None
    agreement: float
    independent_reviewers: int
    notes: list[str]
    expected_mode: str | None
    root_cause_support: float


class EnrichedEpisode(Record):
    episode: Episode
    review: ReviewSummary
    machine_id: str | None
    platform: str | None
    software_release: str | None
    expected_failure_mode: str | None
    expected_mode_basis: Literal["reviewer_consensus", "unknown"]
    downtime_hours: float = Field(ge=0)
    impact_basis: Literal["historical_mode_mean", "historical_population_mean", "unavailable"]


class LabeledEpisode(Record):
    input: EnrichedEpisode
    label: Label


class EvalCase(Record):
    """A replay input and references, not an asserted ground-truth eval answer."""

    episode_id: str
    input: str
    expected_category: Category
    expected_failure_mode: str | None
    expected_mode_basis: str
    tool_calls: list[dict[str, object]]
    review_notes: list[str]


class Cluster(Record):
    id: str
    category: Category
    condition: str
    route: Route
    handoff: str
    evidence_summaries: list[str]
    frequency: int
    mean_downtime_hours: float
    score: float
    episode_ids: list[str]
    representative_episode_ids: list[str]
    platforms: list[str]
    software_releases: list[str]
    expected_failure_modes: list[str]
    eval_cases: list[EvalCase]


class Report(Record):
    source: Literal["synthetic", "real"]
    classifier: str
    episode_count: int
    episode_ids: list[str]
    reviewed_count: int
    uncertain_count: int
    reviewer_agreement: dict[str, ReviewerAgreement]
    clusters: list[Cluster]
    labels: dict[str, Label]
    unclassified: list[EnrichedEpisode]
    errors: dict[str, str]
    limitations: list[str]
