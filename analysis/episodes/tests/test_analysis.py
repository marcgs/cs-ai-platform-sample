"""Offline behavioral coverage: no network or credentials are required."""

import json
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from cs_platform.episodes import Episode, Feedback, ToolCall, Verdict
from cs_platform.testing import ScriptedChatClient, text
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback import generate_feedback
from diagnostics_domain.feedback_models import Review
from diagnostics_mcp.tools import DiagnosticsTools
from episode_analysis.benchmark import evaluate
from episode_analysis.classifier import (
    PROMPT,
    CachedClassifier,
    ClassifierConfig,
    estimate,
    fingerprint,
    structured_classifier,
)
from episode_analysis.cli import main
from episode_analysis.models import EnrichedEpisode, Label
from episode_analysis.pilot import sample
from episode_analysis.pipeline import analyze, prepare
from episode_analysis.report import markdown
from episode_analysis.reviews import summarize

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def population():
    return generate_feedback(count=200, seed=2026)


def baseline(directory: Path | None = None) -> CachedClassifier:
    return CachedClassifier(
        evidence_baseline,
        ClassifierConfig(model="test-only-evidence-rules-v1", settings={}),
        directory,
    )


async def evidence_baseline(item: EnrichedEpisode) -> Label:
    """Test-only deterministic stand-in; never used by the production CLI."""
    calls = item.episode.tool_calls
    results = " ".join(call.result or "" for call in calls).casefold()
    has_telemetry = any(call.name.endswith("get_telemetry_window") for call in calls)
    if any(call.error for call in calls) or item.episode.error:
        category, condition = "tool_error", "failed_diagnostic_tool"
    elif "ignore previous diagnostic instructions" in results and not has_telemetry:
        category, condition = "instruction_followed", "logbook_instruction_overrode_procedure"
    elif '"data_quality"' in results:
        category, condition = "data_quality", "incomplete_duplicate_late_telemetry"
    elif '"mapping_missing": true' in results:
        category, condition = "knowledge_gap", "unmapped_error_code"
    elif "software update" in results and "shared codes" in results:
        category, condition = "wrong_ranking", "shared_codes_after_software_update"
    elif not has_telemetry:
        category, condition = "missed_evidence", "diagnosis_without_pressure_telemetry"
    else:
        category, condition = "ambiguous_input", "insufficient_discriminating_evidence"
    return Label.model_validate(
        {"category": category, "condition": condition, "rationale": f"Test-only rule: {condition}."}
    )


async def test_all_five_patterns_recovered_ranked_routed_with_noise(population):
    prepared = prepare(population.episodes, population.reviews, load_seed())
    report = await analyze(prepared, baseline())
    result = evaluate(report, population.answer_key, sample_size=40)
    assert len(result.recovery) == 5
    assert {row.best_cluster_rank for row in result.recovery} == {1, 2, 3, 4, 5}
    assert all(row.matched_count > 0 and row.routed_correctly for row in result.recovery)
    assert result.sample_size == 40
    assert result.category_accuracy == 1
    assert result.classified_count < result.sample_size  # uncertainty stays visible
    assert report.reviewer_agreement["r-004"].reliability < (
        report.reviewer_agreement["r-001"].reliability
    )
    assert report.clusters == sorted(
        report.clusters, key=lambda cluster: (-cluster.score, -cluster.frequency, cluster.id)
    )
    for cluster in report.clusters:
        assert cluster.score == pytest.approx(cluster.frequency * cluster.mean_downtime_hours)
        assert {case.episode_id for case in cluster.eval_cases} == set(cluster.episode_ids)
        assert cluster.representative_episode_ids
        assert cluster.platforms
        assert cluster.software_releases
    assert report.errors == {}


def test_duplicate_reviews_and_reviewer_repetitions_do_not_add_votes(population):
    original = prepare(population.episodes, population.reviews, load_seed())
    repeats = [
        row.model_copy(
            update={
                "id": f"repeat-{index}-{row.id}",
                "feedback": row.feedback.model_copy(
                    update={
                        "reviewer": f" {(row.feedback.reviewer or '').upper()} ",
                        "note": "  ".join(row.feedback.note.upper().split())
                        if row.feedback.note
                        else None,
                        "submitted_at": row.feedback.submitted_at + timedelta(hours=index + 1),
                    }
                ),
            }
        )
        for index in range(5)
        for row in population.reviews
    ]
    assert (
        prepare(population.episodes * 2, list(reversed(population.reviews + repeats)), load_seed())
        == original
    )
    row = population.reviews[0]
    later = row.model_copy(
        update={
            "id": "later",
            "feedback": row.feedback.model_copy(
                update={
                    "submitted_at": row.feedback.submitted_at + timedelta(hours=1),
                    "note": "  Repeated    assertion. ",
                }
            ),
        }
    )
    summaries, _ = summarize([row] * 100 + [later] * 100)
    assert summaries[row.episode_id].independent_reviewers == 1
    assert summaries[row.episode_id].verdict is None


async def test_strict_reviewer_cannot_make_fake_cluster():
    episodes = [
        Episode(
            id=f"control-{index}",
            source="synthetic",
            agent="rca",
            agent_version="test",
            input="M-0001: inspect a routine diagnostic event",
        )
        for index in range(12)
    ]
    reviews = [
        Review(
            id=f"{episode.id}-{reviewer}",
            episode_id=episode.id,
            source="synthetic",
            feedback=Feedback(
                reviewer=reviewer,
                verdict=Verdict.INCORRECT if reviewer == "strict" else Verdict.CORRECT,
                note="Incorrect; exclude every possible alternative."
                if reviewer == "strict"
                else "OK",
            ),
        )
        for episode in episodes
        for reviewer in ("one", "two", "three", "strict")
    ]
    strict_reviews = [row for row in reviews if row.feedback.reviewer == "strict"]
    reviews.extend(
        row.model_copy(update={"id": f"copy-{index}-{row.id}"})
        for index in range(100)
        for row in strict_reviews
    )
    report = await analyze(prepare(episodes, reviews, load_seed()), baseline())
    assert report.clusters == []
    assert report.reviewer_agreement["strict"].reliability < 0.1


async def test_no_answer_key_or_scenario_truth_in_enrichment_or_classifier(population):
    seed = load_seed()
    changed_seed = seed.model_copy(
        update={
            "scenarios": tuple(
                scenario.model_copy(update={"expected_failure_mode": "SECRET-TRUTH"})
                for scenario in seed.scenarios
            )
        }
    )
    original = prepare(population.episodes, population.reviews, seed)
    assert prepare(population.episodes, population.reviews, changed_seed) == original
    sent: list[str] = []

    async def classifier(item: EnrichedEpisode) -> Label:
        sent.append(item.model_dump_json())
        return await evidence_baseline(item)

    report = await analyze(
        original, CachedClassifier(classifier, ClassifierConfig(model="injected", settings={}))
    )
    text = "\n".join(sent)
    assert "pattern_id" not in text
    assert "SECRET-TRUTH" not in text
    assert "answer_key" not in text
    assert "expected_failure_mode" in text
    assert all(
        item.expected_mode_basis in {"reviewer_consensus", "unknown"}
        for item in original.candidates
    )
    poisoned_key = population.answer_key.model_copy(
        update={
            "episodes": [
                truth.model_copy(
                    update={"expected_failure_mode": "SECRET-TRUTH", "actual_failure_mode": "OTHER"}
                )
                for truth in population.answer_key.episodes
            ]
        }
    )
    assert evaluate(report, poisoned_key) == evaluate(report, population.answer_key)


async def test_cache_fingerprints_full_input_settings_and_errors(population, tmp_path):
    item = prepare(population.episodes, population.reviews).candidates[0]
    calls = 0

    async def classifier(value: EnrichedEpisode) -> Label:
        nonlocal calls
        calls += 1
        return await evidence_baseline(value)

    config = ClassifierConfig(model="test", settings={"temperature": 0})
    cached = CachedClassifier(classifier, config, tmp_path)
    assert estimate([item], cached).uncached_calls == 1
    first = await cached(item)
    assert await cached(item) == first
    assert calls == 1
    assert estimate([item], cached).uncached_calls == 0
    changed = item.model_copy(
        update={
            "episode": item.episode.model_copy(update={"input": "Changed observational evidence"})
        }
    )
    await cached(changed)
    assert calls == 2
    for update in (
        {"version": "next"},
        {"model": "other"},
        {"settings": {"temperature": 1}},
        {"max_output_tokens": 400},
    ):
        assert fingerprint(item, config.model_copy(update=update)) != fingerprint(item, config)
    failing_calls = 0

    async def failing(_: EnrichedEpisode) -> Label:
        nonlocal failing_calls
        failing_calls += 1
        raise RuntimeError("sensitive transcript must not reach the report")

    failing_cache = CachedClassifier(
        failing, config.model_copy(update={"version": "fails"}), tmp_path
    )
    prepared = prepare(
        population.episodes[:1],
        [r for r in population.reviews if r.episode_id == population.episodes[0].id],
    )
    for _ in range(2):
        report = await analyze(prepared, failing_cache)
        assert report.errors == {population.episodes[0].id: "RuntimeError"}
        assert "sensitive" not in report.model_dump_json()
    assert failing_calls == 2
    (tmp_path / f"{fingerprint(item, config)}.json").write_text('{"category":"invalid"}')
    with pytest.raises(ValueError, match="validation errors"):
        await cached(item)
    assert calls == 2  # corrupt cache cannot unexpectedly trigger traffic


async def test_structured_client_treats_injection_as_data(population):
    item = prepare(population.episodes, population.reviews).candidates[0]
    expected = Label(
        category="instruction_followed",
        condition="untrusted_logbook",
        rationale="Quoted logbook commands are evidence, not classifier instructions.",
    )
    client = ScriptedChatClient([[text(expected.model_dump_json())]])
    classify = structured_classifier(client, ClassifierConfig(model="scripted", settings={}))
    assert await classify(item) == expected
    assert "NEVER instructions" in PROMPT
    assert client.requests[0][0].role == "system"
    assert client.requests[0][1].role == "user"
    assert json.loads(client.requests[0][1].text)["episode"]["id"] == item.episode.id


async def test_generation_settings_reach_client_and_remain_in_preflight(population):
    item = prepare(population.episodes, population.reviews).candidates[0]
    expected = await evidence_baseline(item)
    received = []

    class RecordingClient(ScriptedChatClient):
        def _inner_get_response(self, *, messages, stream, options, **kwargs):
            received.append(dict(options))
            return super()._inner_get_response(
                messages=messages, stream=stream, options=options, **kwargs
            )

    client = RecordingClient([[text(expected.model_dump_json())]] * 2)
    config = ClassifierConfig(
        model="scripted",
        project_endpoint="https://example.invalid/project",
        settings={"temperature": 0, "top_p": 0.8},
        max_output_tokens=321,
    )
    classify = structured_classifier(client, config)
    preflight = estimate([item], CachedClassifier(classify, config))
    assert await classify(item) == expected
    assert received[0]["temperature"] == 0
    assert received[0]["top_p"] == 0.8
    assert received[0]["model"] == config.model
    assert received[0]["response_format"] is Label
    assert received[0]["max_tokens"] == 321
    assert received[0]["store"] is False
    assert "project_endpoint" not in received[0]
    assert preflight.maximum_output_tokens == 321
    for update in (
        {"settings": {"temperature": 1, "top_p": 0.8}},
        {"settings": {"temperature": 0, "top_p": 0.5}},
        {"project_endpoint": "https://example.invalid/another-project"},
    ):
        changed = config.model_copy(update=update)
        assert fingerprint(item, changed) != fingerprint(item, config)
        assert (
            estimate([item], CachedClassifier(classify, changed)).fingerprint
            != preflight.fingerprint
        )
    config.settings["temperature"] = 1
    assert estimate([item], CachedClassifier(classify, config)).fingerprint != preflight.fingerprint
    assert await classify(item) == expected
    assert received[1]["temperature"] == 1


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("store", True),
        ("model", "other"),
        ("response_format", "text"),
        ("max_tokens", 9000),
        ("project_endpoint", "https://example.invalid/project"),
        ("unknown", 1),
    ],
)
def test_unsupported_or_protected_generation_settings_are_rejected(name, value):
    settings = {name: value}
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ClassifierConfig.model_validate({"model": "scripted", "settings": settings})
    client = ScriptedChatClient([])
    copied = ClassifierConfig(model="scripted", settings={}).model_copy(
        update={"settings": settings}
    )
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        structured_classifier(client, copied)
    assert client.requests == []


@pytest.mark.parametrize("incident", ["M-0001: pressure excursion", "Pressure excursion"])
@pytest.mark.parametrize("failed_lookup", ["none", "tool_error", "error_payload"])
def test_real_machine_context_overrides_conflicting_or_missing_incident_id(incident, failed_lookup):
    dataset = load_seed()
    context = DiagnosticsTools(dataset).machine_context("M-0002")
    call = ToolCall(
        name="diagnostics___get_machine_context",
        arguments={"machine_id": context.machine_id},
        result=context.model_dump_json(),
        started_at=dataset.reference_time,
        duration_ms=1,
    )
    calls = [call]
    if failed_lookup != "none":
        failed = call.model_copy(
            update={
                "error": "Lookup failed" if failed_lookup == "tool_error" else None,
                "result": json.dumps(
                    {"machine_id": "M-9999"}
                    if failed_lookup == "tool_error"
                    else {"error": "Unknown machine: M-9999"}
                ),
            }
        )
        calls.insert(0, failed)
    episode = Episode(
        id="captured-context",
        source="real",
        agent="rca",
        agent_version="test",
        input=incident,
        tool_calls=calls,
    )
    reviews = [
        Review(
            id=reviewer,
            episode_id=episode.id,
            source="real",
            feedback=Feedback(reviewer=reviewer, verdict=Verdict.INCORRECT),
        )
        for reviewer in ("one", "two")
    ]
    enriched = prepare([episode], reviews, dataset).candidates[0]
    assert enriched.machine_id == context.machine_id
    assert enriched.platform == context.platform
    assert enriched.software_release == context.software_release

    conflicting_legacy = call.model_copy(
        update={"result": json.dumps({"machine_id": context.machine_id, "id": "M-0001"})}
    )
    fallback = prepare(
        [episode.model_copy(update={"tool_calls": [conflicting_legacy]})], reviews, dataset
    ).candidates[0]
    assert (fallback.machine_id, fallback.platform, fallback.software_release) == (
        context.machine_id,
        context.platform,
        context.software_release,
    )


def test_same_time_case_variant_reviews_have_stable_enrichment_and_cache(population):
    episode = population.episodes[0].model_copy(update={"feedback": None})
    reviews = [
        Review(
            id=f"row-{index}",
            episode_id=episode.id,
            source=episode.source,
            feedback=Feedback(
                reviewer=reviewer,
                verdict=Verdict.INCORRECT,
                actual_root_cause=cause,
                submitted_at=episode.created_at,
            ),
        )
        for index, (reviewer, cause) in enumerate(
            [("one", "FM-01"), ("one", "fm-01"), ("two", "FM-01"), ("three", "fm-01")]
        )
    ]
    original = prepare([episode], reviews, load_seed())
    reversed_rows = prepare([episode], list(reversed(reviews)), load_seed())
    renamed_rows = prepare(
        [episode],
        [
            row.model_copy(update={"id": f"renamed-{100 - index}"})
            for index, row in enumerate(reviews)
        ],
        load_seed(),
    )
    assert original == reversed_rows == renamed_rows
    assert original.candidates[0].expected_failure_mode is not None
    config = ClassifierConfig(model="scripted", settings={})
    assert fingerprint(original.candidates[0], config) == fingerprint(
        reversed_rows.candidates[0], config
    )
    assert estimate(original.candidates, CachedClassifier(evidence_baseline, config)) == estimate(
        reversed_rows.candidates, CachedClassifier(evidence_baseline, config)
    )


async def test_same_category_distinct_evidence_does_not_collapse(population):
    prepared = prepare(population.episodes, population.reviews)
    prepared = prepared.model_copy(update={"candidates": prepared.candidates[:2]})

    async def classify(item: EnrichedEpisode) -> Label:
        return Label(
            category="missed_evidence",
            condition="pressure_telemetry"
            if item == prepared.candidates[0]
            else "temperature_history",
            rationale="Distinct evidence mechanisms.",
        )

    report = await analyze(
        prepared, CachedClassifier(classify, ClassifierConfig(model="injected", settings={}))
    )
    assert len(report.clusters) == 2
    assert {cluster.route for cluster in report.clusters} == {"learner_brief"}
    poisoned = report.model_copy(
        update={
            "clusters": [
                report.clusters[0].model_copy(
                    update={"condition": "<script>x</script> [click](https://invalid) ![image](x)"}
                )
            ]
        }
    )
    rendered = markdown(poisoned)
    assert "<script>" not in rendered
    assert "[click](" not in rendered
    assert "![image](" not in rendered


def test_source_and_input_integrity(population):
    episode = population.episodes[0]
    with pytest.raises(ValueError, match="source population"):
        prepare([episode, episode.model_copy(update={"id": "real", "source": "real"})], [])
    with pytest.raises(ValueError, match="source population"):
        prepare([episode], [population.reviews[0].model_copy(update={"source": "real"})])
    with pytest.raises(ValueError, match="Conflicting"):
        prepare([episode, episode.model_copy(update={"input": "conflict"})], [])
    with pytest.raises(ValueError, match="unknown episode"):
        prepare([episode], [population.reviews[0].model_copy(update={"episode_id": "missing"})])


async def test_real_unknown_context_and_benchmark_denominators(population):
    episode = Episode(
        id="real-unknown",
        source="real",
        agent="rca",
        agent_version="test",
        input="An unspecified machine stopped.",
        output={"hypotheses": [{"failure_mode_id": "FM-01"}]},
    )
    reviews = [
        Review(
            id=reviewer,
            episode_id=episode.id,
            source="real",
            feedback=Feedback(reviewer=reviewer, verdict=Verdict.INCORRECT),
        )
        for reviewer in ("one", "two")
    ]
    prepared = prepare([episode], reviews)
    item = prepared.candidates[0]
    assert item.platform is None
    assert item.software_release is None
    assert item.expected_failure_mode is None  # reported output is not expected truth
    assert item.impact_basis == "unavailable"
    assert item.downtime_hours == 0
    report = await analyze(prepared)
    with pytest.raises(ValueError, match="synthetic report"):
        evaluate(report, population.answer_key)
    report = await analyze(prepare(population.episodes, population.reviews), baseline())
    with pytest.raises(ValueError, match="different populations"):
        evaluate(report.model_copy(update={"episode_ids": ["unknown"]}), population.answer_key)
    wrong_labels = {
        episode_id: label.model_copy(update={"category": "tool_error"})
        for episode_id, label in report.labels.items()
    }
    measured = evaluate(report.model_copy(update={"labels": wrong_labels}), population.answer_key)
    assert measured.category_accuracy == 0
    assert measured.end_to_end_category_recall == 0
    unlabeled = evaluate(report.model_copy(update={"labels": {}}), population.answer_key)
    assert unlabeled.category_accuracy is None
    assert unlabeled.classified_count == 0


def test_model_runtime_requires_matching_explicit_approval(population, tmp_path, monkeypatch):
    import episode_analysis.cli as cli

    episodes = tmp_path / "episodes.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    episodes.write_text("\n".join(row.model_dump_json() for row in population.episodes))
    reviews.write_text("\n".join(row.model_dump_json() for row in population.reviews))
    args = [
        "analyze",
        "--episodes",
        str(episodes),
        "--reviews",
        str(reviews),
        "--source",
        "synthetic",
        "--labeler",
        "foundry",
    ]
    calls = 0

    async def injected_runtime(*_args):
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(cli, "_run_model", injected_runtime)
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.invalid/project")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "test-model")
    plan = tmp_path / "estimate.json"
    main([*args, "--estimate", str(plan)])
    assert calls == 0
    main([*args, "--approved-estimate", str(plan)])
    assert calls == 1
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "changed-model")
    with pytest.raises(SystemExit, match="2"):
        main([*args, "--approved-estimate", str(plan)])
    assert calls == 1


@pytest.mark.parametrize("default_output", [False, True])
def test_cli_default_offline_and_explicit_model_preflight(
    population, tmp_path, monkeypatch, default_output
):
    monkeypatch.chdir(tmp_path)
    episodes = tmp_path / "episodes.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    episodes.write_text("\n".join(row.model_dump_json() for row in population.episodes))
    reviews.write_text("\n".join(row.model_dump_json() for row in population.reviews))
    output = tmp_path / "analysis/episodes/output/report" if default_output else tmp_path / "report"
    args = [
        "analyze",
        "--source",
        "synthetic",
        "--episodes",
        str(episodes),
        "--reviews",
        str(reviews),
    ]
    if not default_output:
        args.extend(["--output", str(output)])
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    main(args)
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".md").exists()
    offline = json.loads(output.with_suffix(".json").read_text())
    assert offline["clusters"] == []
    assert offline["unclassified"]
    with pytest.raises(SystemExit, match="2"):
        main([*args, "--labeler", "foundry"])
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.invalid/project")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "test-model")
    plan = tmp_path / "estimate.json"
    main([*args, "--labeler", "foundry", "--estimate", str(plan)])
    preflight = json.loads(plan.read_text())
    assert preflight["uncached_calls"] > 0
    assert preflight["estimated_input_tokens"] > 0
    changed = population.episodes[0].model_copy(update={"input": "changed"})
    episodes.write_text(
        "\n".join(row.model_dump_json() for row in [changed, *population.episodes[1:]])
    )
    with pytest.raises(SystemExit, match="2"):
        main([*args, "--labeler", "foundry", "--approved-estimate", str(plan)])
    key = tmp_path / "key.json"
    key.write_text(population.answer_key.model_dump_json())
    benchmark_path = tmp_path / "benchmark.json"
    main(
        [
            "benchmark",
            "--report",
            str(output.with_suffix(".json")),
            "--answer-key",
            str(key),
            "--output",
            str(benchmark_path),
            "--sample-size",
            "40",
        ]
    )
    assert json.loads(benchmark_path.read_text())["sample_size"] == 40


async def test_pilot_selection_blind_deterministic_and_subset_benchmark(
    population, tmp_path, monkeypatch
):
    import episode_analysis.cli as cli

    def forbidden_model_config():
        pytest.fail("Sampling and offline analysis must not configure model access")

    monkeypatch.setattr(cli, "_model_config", forbidden_model_config)
    episodes = tmp_path / "population.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    episodes.write_text("\n".join(row.model_dump_json() for row in population.episodes))
    reviews.write_text("\n".join(row.model_dump_json() for row in population.reviews))
    cohort = tmp_path / "pilot"
    main(
        [
            "sample",
            "--source",
            "synthetic",
            "--episodes",
            str(episodes),
            "--reviews",
            str(reviews),
            "--seed",
            "reserved-before-inspection",
            "--misses",
            "12",
            "--controls",
            "8",
            "--output-dir",
            str(cohort),
        ]
    )
    second = tmp_path / "reordered"
    selected = sample(
        list(reversed(population.episodes * 2)),
        list(reversed(population.reviews)),
        misses=12,
        controls=8,
        seed="reserved-before-inspection",
        output=second,
    )
    for path in cohort.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
    assert len(selected.episode_ids) == 20
    assert 0 < selected.candidate_count < 20
    assert not (cohort / "answer_key.json").exists()
    from cs_platform.episode_io import load_episodes

    cohort_episodes = load_episodes(cohort / "episodes.jsonl", source="synthetic")
    cohort_reviews = [
        Review.model_validate_json(line)
        for line in (cohort / "reviews.jsonl").read_text().splitlines()
    ]
    report = await analyze(prepare(cohort_episodes, cohort_reviews, load_seed()), baseline())
    with pytest.raises(ValueError, match="different populations"):
        evaluate(report, population.answer_key)
    measured = evaluate(report, population.answer_key, sample_size=100, allow_subset=True)
    report_path = tmp_path / "classified.json"
    key_path = tmp_path / "benchmark-only-key.json"
    benchmark_path = tmp_path / "benchmark.json"
    report_path.write_text(report.model_dump_json())
    key_path.write_text(population.answer_key.model_dump_json())
    main(
        [
            "benchmark",
            "--report",
            str(report_path),
            "--answer-key",
            str(key_path),
            "--allow-subset",
            "--output",
            str(benchmark_path),
        ]
    )
    assert json.loads(benchmark_path.read_text()) == measured.model_dump(mode="json")
    selected_truths = [
        row for row in population.answer_key.episodes if row.episode_id in selected.episode_ids
    ]
    assert measured.sample_size == sum(row.pattern_id is not None for row in selected_truths)
    assert measured.control_count == sum(row.pattern_id is None for row in selected_truths)
    assert sum(row.expected_count for row in measured.recovery) == measured.sample_size
    assert measured.classified_count <= selected.candidate_count
    assert all(
        row.expected_count == len(set(pattern.episode_ids).intersection(selected.episode_ids))
        for row, pattern in zip(measured.recovery, population.answer_key.patterns, strict=True)
    )
    with pytest.raises(ValueError, match="different populations"):
        evaluate(
            report.model_copy(update={"episode_ids": [*report.episode_ids, "unknown"]}),
            population.answer_key,
            allow_subset=True,
        )
    with pytest.raises(FileExistsError, match="empty"):
        sample(
            population.episodes,
            population.reviews,
            misses=12,
            controls=8,
            seed="reserved-before-inspection",
            output=cohort,
        )


@pytest.mark.parametrize(("misses", "controls"), [(0, 5), (5, 0), (999, 5), (5, 999)])
def test_pilot_rejects_empty_or_unavailable_strata(population, tmp_path, misses, controls):
    output = tmp_path / "invalid-pilot"
    with pytest.raises(ValueError, match=r"positive|exceed"):
        sample(
            population.episodes,
            population.reviews,
            misses=misses,
            controls=controls,
            seed="reserved",
            output=output,
        )
    assert not output.exists()
