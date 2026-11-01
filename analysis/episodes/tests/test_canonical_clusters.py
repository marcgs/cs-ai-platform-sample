"""L8 contract tests use hand-authored observations, never a new cohort or answer key."""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter, ValidationError

from cs_platform.episodes import Episode, Feedback, Verdict
from diagnostics_domain.feedback_models import Review
from episode_analysis.classifier import PROMPT, CachedClassifier, ClassifierConfig
from episode_analysis.models import EnrichedEpisode, Label, Report
from episode_analysis.pipeline import analyze, prepare
from episode_analysis.report import markdown, write_report
from episode_analysis.vocabulary import CONDITIONS, Condition, canonical_condition, cluster_key

if TYPE_CHECKING:
    from pathlib import Path


def observations() -> tuple[list[Episode], list[Review]]:
    episodes = [
        Episode(
            id=f"observed-{index}",
            source="synthetic",
            agent="rca",
            agent_version="test",
            input="M-0002: chamber pressure excursion",
        )
        for index in range(2)
    ]
    reviews = [
        Review(
            id=f"{episode.id}-{reviewer}",
            episode_id=episode.id,
            source="synthetic",
            feedback=Feedback(
                reviewer=reviewer,
                verdict=Verdict.INCORRECT,
                actual_root_cause="FM-02",
                submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        for episode in episodes
        for reviewer in ("one", "two", "three")
    ]
    return episodes, reviews


@pytest.mark.parametrize(
    "spelling",
    [
        "prompt_injection_logbook",
        "prompt_injection_in_logbook",
        " Prompt injection in LOGBOOK ",
        "logbook_instruction_overrode_procedure",
        "untrusted_logbook",
    ],
)
def test_known_spellings_share_one_closed_condition(spelling):
    label = Label(
        category="instruction_followed",
        condition=spelling,
        rationale="Observed instruction obeyed.",
    )
    assert label.condition == canonical_condition(spelling) == "prompt_injection_logbook"
    assert cluster_key(label.category, spelling) == cluster_key(
        label.category, "prompt_injection_logbook"
    )


@pytest.mark.parametrize("value", ["new_free_text_synonym", "M-0002", "", "FM-99", None, 7])
def test_unrecognized_conditions_cannot_enter_labels(value):
    with pytest.raises(ValidationError):
        Label.model_validate(
            {"category": "missed_evidence", "condition": value, "rationale": "Observed."}
        )


def test_structured_condition_schema_is_closed_and_canonical():
    schema = Label.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"category", "condition", "rationale"}
    conditions = schema["$defs"]["Condition"]["enum"]
    assert set(conditions) == set(CONDITIONS)
    assert "prompt_injection_in_logbook" not in conditions
    for condition in CONDITIONS:
        assert TypeAdapter(Condition).validate_python(condition) == condition
        assert canonical_condition(condition) == condition


def test_provenance_rejects_conflicting_review_ids():
    episodes, reviews = observations()
    conflict = reviews[0].model_copy(
        update={"feedback": reviews[0].feedback.model_copy(update={"actual_root_cause": "FM-01"})}
    )
    with pytest.raises(ValueError, match="Conflicting duplicate review"):
        prepare(episodes, [*reviews, conflict])


async def test_alias_grouping_and_keys_survive_order_and_wording_changes():
    episodes, reviews = observations()

    async def classify(item: EnrichedEpisode) -> Label:
        return Label.model_validate(
            {
                "category": "instruction_followed",
                "condition": "prompt_injection_in_logbook"
                if item.episode.id == episodes[0].id
                else "logbook_instruction_overrode_procedure",
                "rationale": f"Observed evidence in {item.episode.id}.",
            }
        )

    config = ClassifierConfig(model="scripted", settings={})
    original = await analyze(prepare(episodes, reviews), CachedClassifier(classify, config))
    reversed_report = await analyze(
        prepare(list(reversed(episodes)), list(reversed(reviews))),
        CachedClassifier(classify, config),
    )
    assert original == reversed_report
    assert len(original.clusters) == 1
    cluster = original.clusters[0]
    assert cluster.frequency == 2
    assert cluster.id == "ddb5e9dec4067f4a"
    assert cluster.id == cluster_key("instruction_followed", "prompt_injection_logbook")

    async def reworded(_: EnrichedEpisode) -> Label:
        return Label.model_validate(
            {
                "category": "instruction_followed",
                "condition": "PROMPT INJECTION LOGBOOK",
                "rationale": "Entirely different explanatory wording.",
            }
        )

    changed = await analyze(prepare(episodes, reviews), CachedClassifier(reworded, config))
    assert changed.clusters[0].id == cluster.id
    assert changed.clusters[0].episode_ids == cluster.episode_ids
    assert cluster_key("missed_evidence", "pressure_telemetry") != cluster_key(
        "missed_evidence", "temperature_history"
    )
    assert cluster_key("missed_evidence", "pressure_telemetry") != cluster_key(
        "wrong_ranking", "pressure_telemetry"
    )


async def test_unknown_classifier_condition_remains_an_explicit_failure():
    episodes, reviews = observations()

    async def invalid(_: EnrichedEpisode) -> Label:
        return Label.model_validate(
            {
                "category": "missed_evidence",
                "condition": "invented_synonym",
                "rationale": "Observed.",
            }
        )

    report = await analyze(
        prepare(episodes, reviews),
        CachedClassifier(invalid, ClassifierConfig(model="scripted", settings={})),
    )
    assert report.clusters == []
    assert report.labels == {}
    assert report.errors == {episode.id: "ValidationError" for episode in episodes}
    assert {item.episode.id for item in report.unclassified} == {item.id for item in episodes}


async def test_report_preserves_exact_independent_review_evidence(tmp_path: Path):
    episodes, reviews = observations()
    episodes[0].truncated.append("tool_calls")
    old = reviews[0]
    revision = old.model_copy(
        update={
            "id": "revised-one",
            "feedback": old.feedback.model_copy(
                update={
                    "reviewer": " ONE ",
                    "submitted_at": old.feedback.submitted_at + timedelta(hours=1),
                }
            ),
        }
    )
    dissent = reviews[2].model_copy(
        update={"feedback": reviews[2].feedback.model_copy(update={"actual_root_cause": "FM-01"})}
    )
    evidence = [*reviews[:2], dissent, *reviews[3:], revision, revision]

    async def classify(_: EnrichedEpisode) -> Label:
        return Label(
            category="missed_evidence",
            condition="pressure_telemetry",
            rationale="Necessary pressure data was not used.",
        )

    report = await analyze(
        prepare(episodes, evidence),
        CachedClassifier(classify, ClassifierConfig(model="scripted", settings={})),
    )
    prefix = tmp_path / "report"
    write_report(report, prefix)
    restored = Report.model_validate_json(prefix.with_suffix(".json").read_text())
    assert restored == report
    assert restored.schema_version == "episode-analysis-v2"
    with pytest.raises(ValidationError, match="schema_version"):
        Report.model_validate(report.model_dump(exclude={"schema_version"}))
    legacy = report.model_dump()
    legacy["clusters"][0]["eval_cases"][0].pop("review_summary")
    with pytest.raises(ValidationError, match="review_summary"):
        Report.model_validate(legacy)
    case = next(case for case in report.clusters[0].eval_cases if case.episode_id == episodes[0].id)
    assert case.capture_truncated == ["tool_calls"]
    assert case.capture_status == episodes[0].status
    assert case.capture_created_at == episodes[0].created_at
    assert case.capture_completed_at == episodes[0].completed_at
    for field in (
        "capture_truncated",
        "capture_status",
        "capture_created_at",
        "capture_completed_at",
    ):
        missing_capture = report.model_dump()
        missing_capture["clusters"][0]["eval_cases"][0].pop(field)
        with pytest.raises(ValidationError, match=field):
            Report.model_validate(missing_capture)
    assert case.source_review_ids == sorted(["revised-one", reviews[1].id, dissent.id])
    assert sorted(review.id for review in case.source_reviews) == case.source_review_ids
    assert len(case.source_reviews) == case.review_summary.independent_reviewers == 3
    assert case.review_summary.verdict == "incorrect"
    assert case.review_summary.agreement == 1
    assert case.review_summary.expected_mode == case.expected_failure_mode == "FM-02"
    assert case.review_summary.root_cause_support == pytest.approx(2 / 3)
    assert (
        sum(
            review.feedback.actual_root_cause == case.expected_failure_mode
            for review in case.source_reviews
        )
        == 2
    )
    assert "revised" in markdown(report)
    assert "Stable key:" in markdown(report)
    assert "root" in markdown(report)


async def test_root_cause_disagreement_is_not_silently_promoted():
    episodes, reviews = observations()
    episode = episodes[0]
    evidence = [
        row.model_copy(
            update={
                "feedback": row.feedback.model_copy(
                    update={"actual_root_cause": f"FM-0{index + 1}"}
                )
            }
        )
        for index, row in enumerate(reviews[:3])
    ]

    async def classify(_: EnrichedEpisode) -> Label:
        return Label(
            category="missed_evidence", condition="pressure_telemetry", rationale="Observed."
        )

    report = await analyze(
        prepare([episode], evidence),
        CachedClassifier(classify, ClassifierConfig(model="scripted", settings={})),
    )
    case = report.clusters[0].eval_cases[0]
    assert case.review_summary.verdict == "incorrect"
    assert case.review_summary.expected_mode is None
    assert case.expected_failure_mode is None
    assert case.expected_mode_basis == "unknown"
    assert case.review_summary.root_cause_support == pytest.approx(1 / 3)
    assert len(case.source_review_ids) == 3


@pytest.mark.parametrize("cause", [" ", "\n\t"])
async def test_blank_root_cause_claims_are_not_consensus(cause: str):
    episodes, reviews = observations()
    reviews = [
        row.model_copy(
            update={"feedback": row.feedback.model_copy(update={"actual_root_cause": cause})}
        )
        for row in reviews
    ]

    async def classify(_: EnrichedEpisode) -> Label:
        return Label(
            category="missed_evidence", condition="pressure_telemetry", rationale="Observed."
        )

    report = await analyze(
        prepare(episodes, reviews),
        CachedClassifier(classify, ClassifierConfig(model="scripted", settings={})),
    )
    for case in report.clusters[0].eval_cases:
        assert case.review_summary.verdict == "incorrect"
        assert case.review_summary.expected_mode is None
        assert case.review_summary.root_cause_support == 0
        assert case.expected_failure_mode is None
        assert case.expected_mode_basis == "unknown"


def test_identical_review_ties_retain_deterministic_provenance():
    episodes, reviews = observations()
    copies = [row.model_copy(update={"id": f"copy-{row.id}"}) for row in reviews]
    original = prepare(episodes, [*reviews, *copies])
    assert original == prepare(episodes, list(reversed([*reviews, *copies])))
    assert all(len(rows) == 3 for rows in original.source_reviews.values())


def test_prompt_examples_are_only_from_existing_train_split():
    from pathlib import Path

    manifest = Path(__file__).parents[3] / "evals/rca/src/rca_evals/cases.jsonl"
    train_ids = {
        row["id"]
        for line in manifest.read_text().splitlines()
        if (row := json.loads(line)).get("split") == "train"
    }
    example_ids = set(re.findall(r"SC-\d{3}", PROMPT))
    assert example_ids
    assert example_ids <= train_ids
