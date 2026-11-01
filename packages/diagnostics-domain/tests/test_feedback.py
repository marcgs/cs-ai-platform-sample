import json
from collections import Counter
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
from diagnostics_domain.feedback_replay import (
    execute_tool_call,
    replay_episode,
    tool_fingerprint,
)
from diagnostics_domain.feedback_transcripts import choose_scenario, make_transcript
from diagnostics_domain.tools import DiagnosticsTools
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
    assert (
        "update"
        in next(
            call.result or "" for call in overlap.tool_calls if call.name == "get_logbook"
        ).lower()
    )
    mapping = misses["missing_code_mapping"]
    assert any('"possible_causes": []' in (call.result or "") for call in mapping.tool_calls)
    data = misses["data_quality"]
    assert any(
        "data_quality" in (call.result or "") or "collection" in (call.result or "")
        for call in data.tool_calls
    )
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
                cited = next(event for event in events["events"] if event["ref"] == evidence.ref)
                assert cited["code"] == code
                assert evidence.excerpt == f"Observed {cited['code']}."


@pytest.mark.parametrize("failed", [False, True])
def test_update_context_matches_logbook_without_mutating_seed(failed: bool) -> None:
    dataset = load_seed()
    original = dataset.model_dump_json()
    rng = Random(42)
    scenario = choose_scenario(dataset, 1, rng)
    machine = dataset.machine(scenario.machine_id)
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
    entries = json.loads(next(call.result or "{}" for call in calls if call.name == "get_logbook"))
    assert any("update" in entry["text"].lower() for entry in entries["entries"])
    assert context == DiagnosticsTools(dataset).machine_context(machine.id).model_dump(mode="json")
    assert dataset.model_dump_json() == original


@pytest.mark.parametrize("seed", [7, 42])
def test_missing_mapping_controls_use_real_telemetry_and_service_clues(seed: int) -> None:
    dataset = load_seed()
    original = dataset.model_dump_json()
    population = generate_feedback(count=100, seed=seed)
    checked: Counter[str] = Counter()
    for episode in population.episodes:
        if not any(
            call.name == "lookup_error_code" and call.arguments["code"] == "EC-9901"
            for call in episode.tool_calls
        ):
            continue
        hypothesis = RcaReport.model_validate(episode.output).hypotheses[0]
        searches = [call for call in episode.tool_calls if call.name == "azure_ai_search"]
        assert not searches
        if hypothesis.failure_mode_id == "unknown":
            checked["failed"] += 1
            continue
        assert any(item.source == "get_telemetry_window" for item in hypothesis.evidence)
        assert any(item.source == "logbook" for item in hypothesis.evidence)
        code = json.loads(
            next(
                call.result or "{}"
                for call in episode.tool_calls
                if call.name == "lookup_error_code"
            )
        )
        assert code["ref"] == "EC-9901"
        assert code["possible_causes"] == []
        assert replay_episode(episode).replayable
        checked["correct"] += 1
    assert checked == {"failed": 10, "correct": 10}
    assert dataset.model_dump_json() == original


def test_additive_feedback_seed_preserves_all_existing_records_and_tool_results() -> None:
    from diagnostics_domain.feedback_seed import extend_feedback_seed

    extended = load_seed()
    existing_ids = {machine.id for machine in extended.machines[:52]}
    original = extended.model_copy(
        update={
            "machines": extended.machines[:52],
            "error_codes": tuple(code for code in extended.error_codes if code.code != "EC-9901"),
            "error_events": tuple(
                item for item in extended.error_events if item.machine_id in existing_ids
            ),
            "telemetry": tuple(
                item for item in extended.telemetry if item.machine_id in existing_ids
            ),
            "logbook": tuple(item for item in extended.logbook if item.machine_id in existing_ids),
        }
    )
    assert extend_feedback_seed(original) == extended
    before = original.model_dump(mode="json")
    after = extended.model_dump(mode="json")
    for field, records in before.items():
        assert (
            after[field][: len(records)] if isinstance(records, list) else after[field]
        ) == records
    old_tools, new_tools = DiagnosticsTools(original), DiagnosticsTools(extended)
    for machine_id in sorted(existing_ids):
        assert old_tools.machine_context(machine_id).model_dump_json() == (
            new_tools.machine_context(machine_id).model_dump_json()
        )
        for hours in (24, 48, 168):
            assert old_tools.error_events(machine_id, hours).model_dump_json() == (
                new_tools.error_events(machine_id, hours).model_dump_json()
            )
        assert old_tools.logbook(machine_id).model_dump_json() == (
            new_tools.logbook(machine_id).model_dump_json()
        )
        for signal in old_tools.machine_context(machine_id).signals:
            assert old_tools.telemetry_window(machine_id, signal.name).model_dump_json() == (
                new_tools.telemetry_window(machine_id, signal.name).model_dump_json()
            )
    for code in original.error_codes:
        assert old_tools.error_code(code.code).model_dump_json() == (
            new_tools.error_code(code.code).model_dump_json()
        )


@pytest.mark.parametrize("index", range(4))
def test_feedback_scenario_decisive_refs_resolve_to_its_copied_machine(index: int) -> None:
    from diagnostics_domain.feedback_seed import feedback_scenarios

    dataset = load_seed()
    unchanged = dataset.model_dump_json()
    original = dataset.scenarios[index]
    copied = feedback_scenarios(dataset)[index]
    tools = DiagnosticsTools(dataset)
    events = tools.error_events(copied.machine_id, hours=168)
    logbook = tools.logbook(copied.machine_id)
    signal = dataset.failure_mode(copied.expected_failure_mode).signature.signal
    observed = {
        tools.telemetry_window(copied.machine_id, signal).ref,
        *(event.ref for event in events.events),
        *(entry.ref for entry in logbook.entries),
    }
    assert set(copied.decisive_refs) <= observed
    assert not set(copied.decisive_refs).intersection(original.decisive_refs)
    assert copied.model_dump(exclude={"machine_id", "decisive_refs"}) == original.model_dump(
        exclude={"machine_id", "decisive_refs"}
    )
    assert any(
        event.ref in copied.decisive_refs and event.code == "EC-9901" for event in events.events
    )
    assert any(entry.ref in copied.decisive_refs for entry in logbook.entries)
    assert dataset.model_dump_json() == unchanged


def test_every_generated_tool_call_replays_and_every_pattern_is_replayable() -> None:
    dataset = load_seed()
    tools = DiagnosticsTools(dataset)
    for seed in (7, 42):
        population = generate_feedback(count=100, seed=seed)
        admitted: set[str] = set()
        for episode in population.episodes:
            result = replay_episode(episode, tools=tools)
            assert result.replayable, result.issues
            assert len(result.fingerprints) == len(episode.tool_calls)
            admitted.add(episode.id)
            for call in episode.tool_calls:
                assert json.loads(call.result or "null") == json.loads(
                    execute_tool_call(call, tools)
                )
            truth = next(
                row for row in population.answer_key.episodes if row.episode_id == episode.id
            )
            if truth.pattern_id == "vacuum_telemetry_omission":
                assert (
                    next(
                        scenario.category
                        for scenario in dataset.scenarios
                        if scenario.machine_id == truth.machine_id
                    )
                    == "clean"
                )
            if truth.pattern_id == "overlapping_codes_after_update":
                reference = json.loads(
                    next(
                        call.result or "{}"
                        for call in episode.tool_calls
                        if call.name == "lookup_error_code"
                    )
                )
                assert len(reference["possible_causes"]) > 1
        assert all(
            set(pattern.episode_ids) <= admitted for pattern in population.answer_key.patterns
        )


def test_replay_rejects_changed_results_and_incomplete_or_unsupported_calls() -> None:
    episode = generate_feedback(count=1).episodes[0]
    original = episode.tool_calls[0]
    prefixed = original.model_copy(update={"name": f"diagnostics___{original.name}"})
    assert tool_fingerprint(original) == tool_fingerprint(prefixed)
    for update in (
        {"result": "{}"},
        {"result": "not JSON"},
        {"result": None},
        {"result_truncated": True},
        {"error": "failed"},
        {"name": "azure_ai_search"},
        {"arguments": {"machine_id": "M-9999"}},
    ):
        changed = original.model_copy(update=update)
        rejected = episode.model_copy(update={"tool_calls": [changed]})
        assert not replay_episode(rejected).replayable
    assert not replay_episode(episode.model_copy(update={"tool_calls": []})).replayable
    assert not replay_episode(episode.model_copy(update={"truncated": ["input"]})).replayable
    assert replay_episode(episode).replayable


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
