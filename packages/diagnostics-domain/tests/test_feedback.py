import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from random import Random

import pytest

from cs_platform.episodes import Episode, Verdict
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback import (
    generate_feedback,
    load_feedback,
    main,
    write_feedback,
)
from diagnostics_domain.feedback_models import AnswerKey, Review
from diagnostics_domain.feedback_transcripts import choose_scenario, make_transcript
from rca_agent.report import RcaReport

FIXTURE = Path(__file__).parent / "fixtures" / "feedback"


def test_generation_is_deterministic_configurable_and_prefix_stable() -> None:
    small = generate_feedback(count=10, seed=7)
    repeat = generate_feedback(count=10, seed=7)
    larger = generate_feedback(count=20, seed=7)
    changed = generate_feedback(count=10, seed=8)
    assert small.model_dump_json() == repeat.model_dump_json()
    assert small.episodes == larger.episodes[:10]
    assert small.reviews == larger.reviews[: len(small.reviews)]
    assert small.episodes != changed.episodes
    with pytest.raises(ValueError, match="positive"):
        generate_feedback(count=0)


def test_episode_schema_patterns_and_answer_key_consistency() -> None:
    population = generate_feedback(count=100)
    truth_by_id = {truth.episode_id: truth for truth in population.answer_key.episodes}
    assert len(truth_by_id) == 100
    assert all(episode.source == "synthetic" for episode in population.episodes)
    pattern_ids: set[str] = set()
    for pattern in population.answer_key.patterns:
        assert len(pattern.episode_ids) == 10
        pattern_ids.update(pattern.episode_ids)
        assert set(pattern.episode_ids) == {
            truth.episode_id for truth in truth_by_id.values() if truth.pattern_id == pattern.id
        }
    assert len(pattern_ids) == 50
    for episode in population.episodes:
        assert Episode.model_validate_json(episode.model_dump_json()) == episode
        report = RcaReport.model_validate(episode.output)
        truth = truth_by_id[episode.id]
        assert report.machine_id == truth.machine_id
        assert report.hypotheses[0].failure_mode_id == truth.actual_failure_mode
        assert (truth.expected_failure_mode == truth.actual_failure_mode) == (
            truth.verdict == Verdict.CORRECT
        )
        completed_at = episode.completed_at
        assert completed_at is not None
        assert episode.created_at < completed_at
        assert all(
            episode.created_at <= call.started_at < completed_at for call in episode.tool_calls
        )
        assert "pattern_id" not in episode.model_dump_json()
        assert episode.feedback is not None
        assert episode.feedback == next(
            review.feedback for review in population.reviews if review.episode_id == episode.id
        )
    assert all(review.episode_id in truth_by_id for review in population.reviews)
    assert all(review.source == "synthetic" for review in population.reviews)


def test_planted_transcripts_are_distinguishable_from_successful_controls() -> None:
    population = generate_feedback(count=10)
    episodes = {episode.id: episode for episode in population.episodes}
    misses = {
        truth.pattern_id: episodes[truth.episode_id]
        for truth in population.answer_key.episodes
        if truth.pattern_id
    }
    vacuum = misses["vacuum_telemetry_omission"]
    assert "get_telemetry_window" not in {call.name for call in vacuum.tool_calls}
    assert "vacuum" in (vacuum.tool_calls[2].result or "")
    overlap = misses["overlapping_codes_after_update"]
    assert "Software update" in next(
        call.result or "" for call in overlap.tool_calls if call.name == "get_logbook"
    )
    mapping = misses["missing_code_mapping"]
    assert any('"mapping_missing": true' in (call.result or "") for call in mapping.tool_calls)
    data = misses["data_quality"]
    assert any('"missing_samples": 9' in (call.result or "") for call in data.tool_calls)
    injection = misses["injection_followed"]
    assert any("Ignore previous" in (call.result or "") for call in injection.tool_calls)
    assert "get_telemetry_window" not in {call.name for call in injection.tool_calls}
    for truth in population.answer_key.episodes:
        if truth.pattern_id is None:
            assert "get_telemetry_window" in {
                call.name for call in episodes[truth.episode_id].tool_calls
            }


def test_error_event_citations_match_the_observed_code_in_compact_transcripts() -> None:
    population = generate_feedback(count=100)
    for episode in population.episodes:
        events = json.loads(
            next(
                call.result or "[]"
                for call in episode.tool_calls
                if call.name == "get_error_events"
            )
        )
        code = next(
            call.arguments["code"]
            for call in episode.tool_calls
            if call.name == "lookup_error_code"
        )
        report = RcaReport.model_validate(episode.output)
        for evidence in report.hypotheses[0].evidence:
            if evidence.source == "error_event":
                cited = next(event for event in events if event["id"] == evidence.ref)
                assert cited["code"] == code
                assert evidence.excerpt == f"Observed {cited['code']}."


@pytest.mark.parametrize("failed", [False, True])
def test_update_context_matches_logbook_without_mutating_seed(failed: bool) -> None:
    dataset = load_seed()
    original = dataset.model_dump_json()
    rng = Random(42)
    scenario = choose_scenario(dataset, 1, rng)
    machine = dataset.machine(scenario.machine_id)
    update = scenario.onset - timedelta(hours=2)
    assert machine.last_software_update != update.date()
    calls, _, _, _ = make_transcript(
        dataset,
        scenario,
        context=1,
        failed=failed,
        started_at=dataset.reference_time,
        rng=rng,
    )
    context = json.loads(
        next(call.result or "{}" for call in calls if call.name == "get_machine_context")
    )
    entries = json.loads(next(call.result or "[]" for call in calls if call.name == "get_logbook"))
    logged = next(entry for entry in entries if entry["id"] == "LB-SYN-UPDATE")
    assert datetime.fromisoformat(logged["timestamp"]) == update
    assert context == {
        **machine.model_dump(mode="json"),
        "last_software_update": update.date().isoformat(),
    }
    assert dataset.model_dump_json() == original


def test_reviewer_population_has_noise_without_turning_assertions_into_truth() -> None:
    population = generate_feedback(count=100)
    truth_by_id = {truth.episode_id: truth for truth in population.answer_key.episodes}
    reviews = population.reviews
    assert len({review.id for review in reviews}) < len(reviews)
    assert len({(review.episode_id, review.feedback) for review in reviews}) < len(reviews)
    assert any(review.feedback.note is None for review in reviews)
    assert any(review.feedback.note in {"OK.", "Check again."} for review in reviews)
    assert any(
        review.feedback.actual_root_cause is not None
        and review.feedback.actual_root_cause
        != truth_by_id[review.episode_id].expected_failure_mode
        for review in reviews
    )
    accuracy: dict[str, list[bool]] = {}
    strict_correct_disagreements = 0
    for review in reviews:
        reviewer = review.feedback.reviewer or ""
        truth = truth_by_id[review.episode_id]
        accuracy.setdefault(reviewer, []).append(review.feedback.verdict == truth.verdict)
        if (
            reviewer == "R-004"
            and truth.verdict == Verdict.CORRECT
            and review.feedback.verdict != truth.verdict
        ):
            strict_correct_disagreements += 1
    assert sum(accuracy["R-001"]) / len(accuracy["R-001"]) > 0.9
    assert sum(accuracy["R-001"]) > sum(accuracy["R-003"])
    assert strict_correct_disagreements > 30
    assert any(
        len({review.feedback.verdict for review in reviews if review.episode_id == episode.id}) > 1
        for episode in population.episodes
    )


def test_fixture_and_generated_bundle_roundtrip(tmp_path: Path) -> None:
    fixture = load_feedback(FIXTURE)
    assert fixture == generate_feedback(count=10, seed=42)
    assert len(fixture.episodes) == 10
    assert len(fixture.answer_key.patterns) == 5
    assert all(isinstance(review, Review) for review in fixture.reviews)
    assert isinstance(fixture.answer_key, AnswerKey)
    generated = generate_feedback(count=11, seed=99)
    destination = tmp_path / "synthetic"
    write_feedback(generated, destination)
    assert load_feedback(destination) == generated
    with pytest.raises(FileExistsError, match="empty"):
        write_feedback(generated, destination)
    assert Counter(truth.verdict for truth in fixture.answer_key.episodes) == {
        Verdict.INCORRECT: 5,
        Verdict.CORRECT: 5,
    }


def test_bundle_refuses_real_or_mismatched_review_input(tmp_path: Path) -> None:
    population = generate_feedback(count=10)
    population.episodes[0].source = "real"
    with pytest.raises(ValueError, match="source-separated"):
        write_feedback(population, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    population.episodes[0].source = "synthetic"
    destination = tmp_path / "synthetic"
    write_feedback(population, destination)
    path = destination / "reviews.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    rows[0]["source"] = "real"
    path.write_text("\n".join(json.dumps(row) for row in rows), "utf-8")
    with pytest.raises(ValueError, match="source-separated"):
        load_feedback(destination)


@pytest.mark.parametrize("damage", ["missing_source", "wrong_membership", "duplicate_truth"])
def test_bundle_rejects_unlabelled_or_inconsistent_answer_key(tmp_path: Path, damage: str) -> None:
    destination = tmp_path / "synthetic"
    write_feedback(generate_feedback(count=10), destination)
    path = destination / "answer_key.json"
    key = json.loads(path.read_text("utf-8"))
    if damage == "missing_source":
        del key["source"]
    elif damage == "wrong_membership":
        key["patterns"][0]["episode_ids"] = []
    else:
        key["episodes"].append(key["episodes"][0])
    path.write_text(json.dumps(key), "utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        load_feedback(destination)


def test_cli_writes_only_explicitly_synthetic_local_files(tmp_path: Path) -> None:
    destination = tmp_path / "synthetic"
    main(["--count", "10", "--seed", "4", "--output-dir", str(destination)])
    assert len(load_feedback(destination).episodes) == 10
    assert sorted(path.name for path in destination.iterdir()) == [
        "answer_key.json",
        "episodes.jsonl",
        "reviews.jsonl",
    ]
