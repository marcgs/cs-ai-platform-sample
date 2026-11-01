"""Analysis contracts deliberately have no dependency on generator truth."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cs_platform.episodes import Episode
from diagnostics_domain.feedback_models import Review
from episode_analysis.vocabulary import Category, Condition, canonical_condition

type Route = Literal["learner_brief", "knowledge_proposal", "backlog"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Label(Record):
    """Fixed category plus a distinguishing, reusable evidence/condition signature."""

    category: Category
    condition: Condition
    rationale: str = Field(min_length=1, max_length=1000)

    @field_validator("condition", mode="before")
    @classmethod
    def normalize_condition(cls, value: object) -> Condition:
        """Accept only known spellings; structured output advertises canonical values only."""
        if not isinstance(value, str):
            raise ValueError("Condition must be a canonical vocabulary string")
        return canonical_condition(value)


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
    capture_truncated: list[str]
    capture_status: Literal["running", "succeeded", "failed"]
    capture_created_at: datetime
    capture_completed_at: datetime | None
    review_notes: list[str]
    review_summary: ReviewSummary
    source_review_ids: list[str]
    source_reviews: list[Review]


class Cluster(Record):
    id: str
    category: Category
    condition: Condition
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
    schema_version: Literal["episode-analysis-v2"]
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
