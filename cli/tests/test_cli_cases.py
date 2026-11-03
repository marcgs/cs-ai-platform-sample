import asyncio
import json
import subprocess
from dataclasses import replace
from importlib import resources
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cs_platform.episodes import Verdict
from cs_platform.evals import EvalTruth, RunOutput, run_suite
from csai.app import app
from csai.case_consensus import review_consensus, reviewer_identity
from csai.case_proposal import CaseProposal, propose_cases, report_digest
from csai.cases import FEEDBACK, MANIFEST
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback import generate_feedback
from diagnostics_domain.feedback_replay import replay_episode
from diagnostics_domain.feedback_seed import feedback_scenarios
from episode_analysis.classifier import CachedClassifier, ClassifierConfig
from episode_analysis.models import EnrichedEpisode, Label, Report, ReviewSummary
from episode_analysis.pipeline import analyze, prepare
from episode_analysis.vocabulary import cluster_key
from rca_evals import load_suite
from rca_evals.evaluators import (
    data_quality_disclosed,
    decisive_evidence_recall,
    injection_resisted,
    ruled_out_correctly,
)
from rca_evals.feedback import load_feedback_cases

if TYPE_CHECKING:
    from pathlib import Path

    from cs_platform.episodes import Episode
    from diagnostics_domain.feedback_replay import ReplayResult

runner = CliRunner()


async def evidence_label(item: EnrichedEpisode) -> Label:
    calls = item.episode.tool_calls
    results = " ".join(call.result or "" for call in calls).casefold()
    telemetry = any(call.name.endswith("get_telemetry_window") for call in calls)
    if "ignore previous instructions" in results and not telemetry:
        category, condition = "instruction_followed", "prompt_injection_logbook"
    elif '"data_quality"' in results:
        category, condition = "data_quality", "incomplete_duplicate_late_telemetry"
    elif any(
        call.name == "lookup_error_code"
        and not json.loads(call.result or "{}").get("possible_causes", [None])
        for call in calls
    ):
        category, condition = "knowledge_gap", "unmapped_error_code"
    elif "software update" in results:
        category, condition = "wrong_ranking", "shared_codes_after_software_update"
    else:
        category, condition = "missed_evidence", "pressure_telemetry"
    return Label.model_validate(
        {"category": category, "condition": condition, "rationale": "Observed test-only evidence."}
    )


@pytest.fixture(scope="module")
def feedback_report():
    population = generate_feedback(count=200, seed=2026)
    classifier = CachedClassifier(
        evidence_label, ClassifierConfig(model="offline-test-evidence", settings={})
    )
    report = asyncio.run(
        analyze(prepare(population.episodes, population.reviews, load_seed()), classifier)
    )
    return population, report


def repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(path)], check=True)
    manifest = path / MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(resources.files("rca_evals").joinpath("cases.jsonl").read_bytes())
    return path


def invoke(report: Report, repo: Path):
    source = repo.parent / "report.json"
    source.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return runner.invoke(
        app, ["--no-azd", "cases", "propose", str(source), "--repository", str(repo)]
    )


def proposal(repo: Path) -> CaseProposal:
    path = next((repo / "docs/iteration-4/proposals").glob("*/proposal.json"))
    return CaseProposal.model_validate_json(path.read_text())


def only_mapping(report: Report) -> Report:
    cluster = next(cluster for cluster in report.clusters if cluster.category == "knowledge_gap")
    candidate = next(
        candidate
        for candidate in cluster.eval_cases
        if all(
            row.feedback.verdict == "incorrect"
            and row.feedback.actual_root_cause in (None, candidate.expected_failure_mode)
            for row in candidate.source_reviews
        )
    )
    return report.model_copy(
        update={
            "review_candidates": [],
            "clusters": [
                cluster.model_copy(
                    update={
                        "eval_cases": [candidate.model_copy(deep=True)],
                        "episode_ids": [candidate.episode_id],
                        "frequency": 1,
                    }
                )
            ],
        },
        deep=True,
    )


def test_public_command_admits_only_planted_review_truth_and_is_idempotent(
    feedback_report, tmp_path: Path
) -> None:
    population, report = feedback_report
    repo = repository(tmp_path / "repo")
    original = (repo / MANIFEST).read_bytes()
    first = invoke(report, repo)
    assert first.exit_code == 0, first.output
    result = proposal(repo)
    assert result.cases
    truths = {row.episode_id: row for row in population.answer_key.episodes}
    candidate_reviews = {
        row.id: row
        for cluster in report.clusters
        for candidate in cluster.eval_cases
        for row in candidate.source_reviews
    }
    for case in result.cases:
        origin = case.provenance
        assert origin is not None
        truth = truths[origin.episode_id]
        assert truth.pattern_id is not None
        assert case.expected["failure_mode"] == truth.expected_failure_mode
        supporting = [candidate_reviews[review_id] for review_id in origin.supporting_review_ids]
        assert len({row.feedback.reviewer for row in supporting}) >= 2
        assert all(
            row.feedback.actual_root_cause == truth.expected_failure_mode for row in supporting
        )
        assert {row.feedback.reviewer for row in supporting} != {"R-004"}
        assert case.cohort == "feedback"
        assert case.split in {"train", "test"}
        assert origin.source == "synthetic"
        assert origin.failure_mode_basis == "reviewer_consensus"
        assert origin.category_basis == "replay_matched_synthetic_scenario"
        assert decisive_evidence_recall(case, RunOutput()) == {}
        assert ruled_out_correctly(case, RunOutput()) == {}
        assert (
            injection_resisted(
                case.model_copy(update={"truth": EvalTruth(category="injection")}), RunOutput()
            )
            == {}
        )
        assert (
            data_quality_disclosed(
                case.model_copy(update={"truth": EvalTruth(category="data_gap")}), RunOutput()
            )
            == {}
        )
        assert case.truth is not None
        assert case.truth.model_dump(exclude_defaults=True) == {"category": case.truth.category}
    duplicates = [
        decision.case_id for decision in result.decisions if decision.status == "duplicate"
    ]
    assert any(value in {f"SC-{number:03d}" for number in range(1, 19)} for value in duplicates)
    assert any(value in {f"SC-{number:03d}" for number in range(19, 51)} for value in duplicates)
    before = {
        path.relative_to(repo): path.read_bytes()
        for path in (repo / "docs/iteration-4/proposals").rglob("*")
        if path.is_file()
    }
    manifest = (repo / FEEDBACK).read_bytes()
    second = invoke(report, repo)
    assert second.exit_code == 0, second.output
    assert second.output == first.output
    assert (repo / FEEDBACK).read_bytes() == manifest
    assert (repo / MANIFEST).read_bytes() == original
    assert before == {path: (repo / path).read_bytes() for path in before}
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"], capture_output=True
    )
    assert head.returncode != 0  # No commit was created, even in the fixture repository.


def test_unclustered_consensus_is_admitted_and_reruns_identically(
    feedback_report, tmp_path: Path
) -> None:
    _, original = feedback_report
    selected = only_mapping(original)
    candidate = selected.clusters[0].eval_cases[0].model_copy(update={"expected_category": None})
    report = selected.model_copy(
        update={"clusters": [], "labels": {}, "review_candidates": [candidate]}
    )
    repo = repository(tmp_path / "repo")
    first = invoke(report, repo)
    assert first.exit_code == 0, first.output
    result = proposal(repo)
    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.provenance is not None
    assert case.provenance.cluster_key is None
    assert "cluster_key" not in case.provenance.model_dump(mode="json")
    assert case.provenance.analysis_category is None
    assert case.truth is not None
    scenario = next(
        scenario
        for scenario in (*load_seed().scenarios, *feedback_scenarios(load_seed()))
        if scenario.machine_id == case.expected["machine_id"]
    )
    assert case.truth.category == scenario.category
    assert case.expected["failure_mode"] == candidate.expected_failure_mode
    before = {
        path.relative_to(repo): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }
    second = invoke(report, repo)
    assert second.exit_code == 0, second.output
    assert second.output == first.output
    assert all((repo / path).read_bytes() == value for path, value in before.items())
    assert load_feedback_cases(repo / FEEDBACK)


@pytest.mark.parametrize("forgery", ["summary", "review_ids", "reviewer"])
def test_unclustered_forged_review_evidence_is_rejected(feedback_report, forgery: str) -> None:
    _, report = feedback_report
    candidate = only_mapping(report).clusters[0].eval_cases[0].model_copy(deep=True)
    if forgery == "summary":
        candidate = candidate.model_copy(
            update={
                "review_summary": candidate.review_summary.model_copy(update={"agreement": 0.99})
            }
        )
    elif forgery == "review_ids":
        candidate.source_review_ids.append("FORGED")
    else:
        candidate.source_reviews[1] = candidate.source_reviews[1].model_copy(
            update={"feedback": candidate.source_reviews[0].feedback}
        )
    result = propose_cases(
        report.model_copy(update={"clusters": [], "labels": {}, "review_candidates": [candidate]}),
        load_suite().cases,
    )
    assert not result.cases
    assert result.decisions[0].status == "rejected"


def test_real_feedback_cannot_borrow_synthetic_category_metadata(feedback_report) -> None:
    _, report = feedback_report
    with pytest.raises(ValueError, match="explicitly synthetic"):
        propose_cases(report.model_copy(update={"source": "real"}), load_suite().cases)


def test_report_wide_candidates_do_not_hide_forged_cluster_category(feedback_report) -> None:
    _, report = feedback_report
    selected = only_mapping(report)
    cluster = selected.clusters[0]
    candidate = cluster.eval_cases[0]
    selected = selected.model_copy(
        update={"review_candidates": [candidate.model_copy(update={"expected_category": None})]}
    )
    assert propose_cases(selected, load_suite().cases).cases
    cluster.eval_cases[0] = candidate.model_copy(update={"expected_category": "wrong_ranking"})
    result = propose_cases(selected, load_suite().cases)
    assert not result.cases
    assert result.decisions[0].status == "rejected"


def test_cluster_review_id_conflict_rejects_other_report_wide_episode(feedback_report) -> None:
    _, report = feedback_report
    selected = only_mapping(report)
    candidate = selected.clusters[0].eval_cases[0]
    admitted = {
        case.provenance.episode_id
        for case in propose_cases(report, load_suite().cases).cases
        if case.provenance is not None
    }
    other = next(
        item
        for item in report.review_candidates
        if item.episode_id in admitted and item.episode_id != candidate.episode_id
    )
    selected = selected.model_copy(
        update={
            "review_candidates": [
                candidate.model_copy(update={"expected_category": None}, deep=True),
                other,
            ]
        }
    )
    assert len(propose_cases(selected, load_suite().cases).cases) == 2
    candidate.source_reviews[0] = candidate.source_reviews[0].model_copy(
        update={"id": other.source_reviews[0].id}
    )
    result = propose_cases(selected, load_suite().cases)
    assert not result.cases
    assert {decision.status for decision in result.decisions} == {"rejected"}


def test_split_pattern_does_not_block_individual_cases(feedback_report) -> None:
    _, report = feedback_report
    cluster = next(cluster for cluster in report.clusters if cluster.category == "knowledge_gap")
    selected = report.model_copy(update={"clusters": [cluster], "review_candidates": []})
    baseline = propose_cases(selected, load_suite().cases)
    assert baseline.cases
    split = []
    labels = dict(report.labels)
    for condition, members in (
        ("pressure_telemetry", cluster.eval_cases[::2]),
        ("temperature_history", cluster.eval_cases[1::2]),
    ):
        key = cluster_key(cluster.category, condition)
        split.append(
            cluster.model_copy(
                update={
                    "id": key,
                    "condition": condition,
                    "eval_cases": members,
                    "episode_ids": [item.episode_id for item in members],
                    "frequency": len(members),
                }
            )
        )
        for candidate in members:
            labels[candidate.episode_id] = labels[candidate.episode_id].model_copy(
                update={"condition": condition}
            )
    result = propose_cases(
        selected.model_copy(update={"clusters": split, "labels": labels}), load_suite().cases
    )
    assert {case.id for case in result.cases} == {case.id for case in baseline.cases}


def test_cli_attaches_all_fresh_cohort_reviews_without_classification(
    feedback_report, tmp_path: Path
) -> None:
    population, _ = feedback_report
    report = asyncio.run(analyze(prepare(population.episodes, population.reviews, load_seed())))
    assert not report.clusters
    assert len(report.review_candidates) == report.reviewed_count
    assert len(report.review_candidates) > len(report.unclassified)
    source = tmp_path / "retained-report.json"
    source.write_text(report.model_copy(update={"review_candidates": []}).model_dump_json())
    episodes = tmp_path / "episodes.jsonl"
    episodes.write_text("".join(item.model_dump_json() + "\n" for item in population.episodes))
    reviews = tmp_path / "reviews.jsonl"
    reviews.write_text("".join(item.model_dump_json() + "\n" for item in population.reviews))
    repo = repository(tmp_path / "repo")
    response = runner.invoke(
        app,
        [
            "--no-azd",
            "cases",
            "propose",
            str(source),
            "--repository",
            str(repo),
            "--episodes",
            str(episodes),
            "--reviews",
            str(reviews),
        ],
    )
    assert response.exit_code == 0, response.output
    result = proposal(repo)
    assert len(result.decisions) == report.reviewed_count
    assert result.cases
    assert all(decision.cluster_key is None for decision in result.decisions)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("mutation", ["cause", "capture"])
def test_cli_rejects_attached_sources_conflicting_with_retained_evidence(
    feedback_report, tmp_path: Path, legacy: bool, mutation: str
) -> None:
    population, _ = feedback_report
    report = asyncio.run(analyze(prepare(population.episodes, population.reviews, load_seed())))
    retained = next(item for item in report.unclassified if item.expected_failure_mode is not None)
    if legacy:
        report = report.model_copy(update={"review_candidates": []})
    changed_episodes = list(population.episodes)
    changed_reviews = list(population.reviews)
    if mutation == "cause":
        mode = "FM-01" if retained.expected_failure_mode != "FM-01" else "FM-02"
        changed_reviews = [
            row.model_copy(
                update={"feedback": row.feedback.model_copy(update={"actual_root_cause": mode})}
            )
            if row.episode_id == retained.episode.id
            else row
            for row in changed_reviews
        ]
    else:
        changed_episodes = [
            item.model_copy(update={"input": item.input + " Changed capture."})
            if item.id == retained.episode.id
            else item
            for item in changed_episodes
        ]
    source = tmp_path / "retained-report.json"
    source.write_text(report.model_dump_json())
    episodes = tmp_path / "episodes.jsonl"
    episodes.write_text("".join(item.model_dump_json() + "\n" for item in changed_episodes))
    reviews = tmp_path / "reviews.jsonl"
    reviews.write_text("".join(item.model_dump_json() + "\n" for item in changed_reviews))
    repo = repository(tmp_path / "repo")
    response = runner.invoke(
        app,
        [
            "--no-azd",
            "cases",
            "propose",
            str(source),
            "--repository",
            str(repo),
            "--episodes",
            str(episodes),
            "--reviews",
            str(reviews),
        ],
    )
    assert response.exit_code == 2, response.output
    assert "conflicts with retained" in response.output
    assert not (repo / FEEDBACK).exists()
    assert subprocess.check_output(
        ["git", "-C", str(repo), "branch", "--show-current"]
    ).strip() == (b"main")


@pytest.mark.parametrize(
    ("mutation", "reason", "k4"),
    [
        ("changed_result", "fingerprint", True),
        ("non_replayable", "Incomplete tool capture", True),
        ("explicit_metadata", "non-replayable", True),
        ("truncated_episode", "Incomplete episode capture", True),
        ("running_episode", "Incomplete episode capture", True),
        ("missing_completion", "Incomplete episode capture", True),
        ("forged_summary", "ReviewSummary", False),
        ("forged_review_id", "source review", False),
        ("copied_identity", "source review", False),
        ("unstable_key", "cluster", False),
    ],
)
def test_public_command_rejects_bad_evidence(
    feedback_report, tmp_path: Path, mutation: str, reason: str, k4: bool
) -> None:
    _, report = feedback_report
    source = only_mapping(report)
    cluster = source.clusters[0]
    candidate = cluster.eval_cases[0]
    if mutation == "changed_result":
        candidate.tool_calls[0]["result"] = "{}"
    elif mutation == "non_replayable":
        candidate.tool_calls[0]["error"] = "Explicitly non-replayable synthetic context"
    elif mutation == "explicit_metadata":
        candidate.tool_calls[0]["replayable"] = False
    elif mutation == "truncated_episode":
        candidate.capture_truncated.append("tool_calls")
    elif mutation == "running_episode":
        candidate = candidate.model_copy(update={"capture_status": "running"})
    elif mutation == "missing_completion":
        candidate = candidate.model_copy(update={"capture_completed_at": None})
    elif mutation == "forged_summary":
        candidate = candidate.model_copy(
            update={
                "review_summary": candidate.review_summary.model_copy(update={"agreement": 0.99})
            }
        )
    elif mutation == "forged_review_id":
        candidate.source_review_ids.append("FORGED")
    elif mutation == "copied_identity":
        original = candidate.source_reviews[0]
        copied = candidate.source_reviews[1]
        assert original.feedback.reviewer is not None
        candidate.source_reviews[1] = copied.model_copy(
            update={
                "feedback": copied.feedback.model_copy(
                    update={"reviewer": f" {original.feedback.reviewer.lower()} "}
                )
            }
        )
    elif mutation == "unstable_key":
        cluster = cluster.model_copy(update={"id": "unstable"})
    source = source.model_copy(
        update={"clusters": [cluster.model_copy(update={"eval_cases": [candidate]})]}
    )
    repo = repository(tmp_path / "repo")
    response = invoke(source, repo)
    assert response.exit_code == 0, response.output
    result = proposal(repo)
    assert not result.cases
    assert result.decisions[0].status == "rejected"
    assert reason.lower() in result.decisions[0].reason.lower()
    assert result.decisions[0].k4 == k4
    body = next((repo / "docs/iteration-4/proposals").glob("*/pr-body.md")).read_text()
    assert "K4: non-replayable" in body


def test_completed_failed_candidate_forwards_actual_lifecycle_to_replay(
    feedback_report, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, report = feedback_report
    source = only_mapping(report)
    cluster = source.clusters[0]
    candidate = cluster.eval_cases[0].model_copy(update={"capture_status": "failed"})
    assert candidate.capture_completed_at is not None
    source = source.model_copy(
        update={"clusters": [cluster.model_copy(update={"eval_cases": [candidate]})]}
    )
    captured: list[Episode] = []

    def replay(episode: Episode) -> ReplayResult:
        captured.append(episode)
        assert episode.status == candidate.capture_status
        assert episode.created_at == candidate.capture_created_at
        assert episode.completed_at == candidate.capture_completed_at
        return replay_episode(episode)

    monkeypatch.setattr("csai.case_proposal.replay_episode", replay)
    repo = repository(tmp_path / "repo")
    response = invoke(source, repo)
    assert response.exit_code == 0, response.output
    assert captured
    assert proposal(repo).cases


@pytest.mark.parametrize("kind", ["single", "disagree", "blank"])
def test_public_command_applies_reviewer_consensus(
    feedback_report, tmp_path: Path, kind: str
) -> None:
    _, report = feedback_report
    report = only_mapping(report)
    candidate = report.clusters[0].eval_cases[0]
    selected = [
        row
        for row in candidate.source_reviews
        if row.feedback.verdict == "incorrect"
        and row.feedback.actual_root_cause == candidate.expected_failure_mode
    ][:2]
    assert len(selected) == 2
    if kind == "single":
        selected = selected[:1]
    elif kind == "disagree":
        selected[1] = selected[1].model_copy(
            update={
                "feedback": selected[1].feedback.model_copy(update={"actual_root_cause": "FM-08"})
            }
        )
    else:
        reviewers = {reviewer_identity(row) for row in selected}
        reviewer = next(
            name for name in report.reviewer_agreement if name.strip().casefold() not in reviewers
        )
        selected.append(
            selected[0].model_copy(
                update={
                    "id": f"{selected[0].id}-blank",
                    "feedback": selected[0].feedback.model_copy(
                        update={"reviewer": reviewer, "actual_root_cause": " \t\n"}
                    ),
                }
            )
        )
    weights = {name: metric.reliability for name, metric in report.reviewer_agreement.items()}
    consensus = review_consensus(
        selected,
        episode_id=candidate.episode_id,
        source_review_ids=[row.id for row in selected],
        reviewer_weights=weights,
    )
    if kind == "blank":
        assert consensus.status == "admit"
    summary = ReviewSummary.model_validate(
        {
            "episode_id": candidate.episode_id,
            "verdict": consensus.verdict,
            "agreement": consensus.agreement,
            "independent_reviewers": consensus.independent_reviewers,
            "notes": consensus.notes,
            "expected_mode": consensus.failure_mode,
            "root_cause_support": consensus.root_cause_support,
        }
    )
    candidate = candidate.model_copy(
        update={
            "source_reviews": selected,
            "source_review_ids": [row.id for row in selected],
            "review_summary": summary,
            "review_notes": consensus.notes,
            "expected_failure_mode": consensus.failure_mode,
            "expected_mode_basis": "reviewer_consensus" if consensus.failure_mode else "unknown",
        }
    )
    report = report.model_copy(
        update={"clusters": [report.clusters[0].model_copy(update={"eval_cases": [candidate]})]}
    )
    repo = repository(tmp_path / "repo")
    response = invoke(report, repo)
    assert response.exit_code == 0, response.output
    result = proposal(repo)
    if kind == "blank":
        assert len(result.cases) == 1, result.decisions
        origin = result.cases[0].provenance
        assert origin is not None
        assert len(origin.supporting_review_ids) == 2
        assert selected[-1].id not in origin.supporting_review_ids
    else:
        assert not result.cases
        assert result.decisions[0].status == ("wait" if kind == "single" else "expert")


def test_legacy_and_forged_cohort_weights_fail_before_branch_changes(
    feedback_report, tmp_path: Path
) -> None:
    _, report = feedback_report
    repo = repository(tmp_path / "repo")
    source = tmp_path / "bad.json"
    data = report.model_dump(mode="json")
    del data["schema_version"]
    source.write_text(json.dumps(data))
    result = runner.invoke(
        app, ["--no-azd", "cases", "propose", str(source), "--repository", str(repo)]
    )
    assert result.exit_code == 2
    weights = dict(report.reviewer_agreement)
    name = next(iter(weights))
    weights[name] = weights[name].model_copy(update={"reliability": 0.999999})
    result = invoke(report.model_copy(update={"reviewer_agreement": weights}), repo)
    assert result.exit_code == 2
    assert "cohort reviewer reliability" in result.output
    assert not (repo / FEEDBACK).exists()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True
        ).stdout.strip()
        == "main"
    )


async def test_feedback_loader_is_additive_non_gating_and_refuses_leakage(
    feedback_report, tmp_path: Path
) -> None:
    _, report = feedback_report
    repo = repository(tmp_path / "repo")
    response = invoke(report, repo)
    assert response.exit_code == 0, response.output
    original = load_suite(feedback_cases=tmp_path / "absent-feedback.jsonl")
    combined = load_suite(feedback_cases=repo / FEEDBACK)
    assert combined.cases[: len(original.cases)] == original.cases
    assert combined.gate_case_ids == original.gate_case_ids
    feedback = combined.cases[len(original.cases) :]
    assert feedback

    async def failing(_):
        return RunOutput(error="Informational feedback case failed")

    result = await run_suite(replace(combined, cases=feedback, evaluators=()), failing, retries=0)
    assert not any(case.gated for case in result.cases)
    assert not result.errored
    assert not result.failures(combined.thresholds)
    path = repo / FEEDBACK
    duplicate = (*feedback, feedback[0])
    path.write_text("".join(case.model_dump_json() + "\n" for case in duplicate))
    with pytest.raises(ValueError, match="duplicate"):
        load_feedback_cases(path, existing=original.cases)
    same_machine = feedback[0].model_copy(
        update={
            "id": "FB-conflict",
            "expected": {**feedback[0].expected, "failure_mode": "FM-08"},
            "split": "test" if feedback[0].split == "train" else "train",
        }
    )
    path.write_text(feedback[0].model_dump_json() + "\n" + same_machine.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="both splits"):
        load_feedback_cases(path, existing=original.cases)
    malformed = feedback[0].model_copy(update={"expected": {"failure_mode": "FM-01"}})
    path.write_text(malformed.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="expected machine_id"):
        load_feedback_cases(path, existing=original.cases)


def test_present_default_feedback_preserves_explicit_seed_baselines(
    feedback_report, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "rca-package"
    package.mkdir()
    for filename in ("cases.jsonl", "thresholds.yaml"):
        source = resources.files("rca_evals").joinpath(filename)
        (package / filename).write_bytes(source.read_bytes())
    absent = tmp_path / "absent-feedback.jsonl"
    baseline = load_suite(feedback_cases=absent)
    _, report = feedback_report
    cases = propose_cases(only_mapping(report), baseline.cases).cases
    assert cases
    (package / "feedback_cases.jsonl").write_text(
        "".join(case.model_dump_json() + "\n" for case in cases)
    )
    monkeypatch.setattr(resources, "files", lambda _: package)
    seeded = load_suite(feedback_cases=absent)
    combined = load_suite()
    assert len(seeded.cases) == 50
    assert len(seeded.gate_case_ids or ()) == 18
    assert combined.cases[:50] == seeded.cases
    assert len(combined.cases) == 50 + len(cases)
    assert combined.gate_case_ids == seeded.gate_case_ids
    assert all(case.cohort == "feedback" for case in combined.cases[50:])


@pytest.mark.parametrize(
    "mutation",
    [
        "cluster_key",
        "review_ids",
        "supporting_review_ids",
        "verdict",
        "tool_fingerprints",
        "identity",
        "category_basis",
    ],
)
def test_feedback_loader_rejects_inconsistent_provenance(
    feedback_report, tmp_path: Path, mutation: str
) -> None:
    _, report = feedback_report
    repo = repository(tmp_path / "repo")
    response = invoke(only_mapping(report), repo)
    assert response.exit_code == 0, response.output
    case = proposal(repo).cases[0]
    provenance = case.provenance
    assert provenance is not None
    if mutation == "identity":
        case = case.model_copy(
            update={"expected": {**case.expected, "machine_id": case.expected["machine_id"] + " "}}
        )
    else:
        updates: dict[str, object] = {
            "cluster_key": "unstable",
            "review_ids": (*provenance.review_ids, provenance.review_ids[0]),
            "supporting_review_ids": (
                *provenance.supporting_review_ids,
                provenance.supporting_review_ids[0],
            ),
            "verdict": Verdict.CORRECT,
            "tool_fingerprints": ("not-a-fingerprint",),
            "category_basis": None,
        }
        case = case.model_copy(
            update={"provenance": provenance.model_copy(update={mutation: updates[mutation]})}
        )
    path = repo / FEEDBACK
    path.write_text(case.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="expected"):
        load_feedback_cases(
            path, existing=load_suite(feedback_cases=tmp_path / "absent-feedback.jsonl").cases
        )


def repository_contents(repo: Path):
    contents = {}
    for path in repo.rglob("*"):
        relative = path.relative_to(repo)
        if ".git" in relative.parts:
            continue
        contents[relative] = (
            path.readlink() if path.is_symlink() else path.read_bytes() if path.is_file() else None
        )
    return contents


def test_public_command_rejects_conflicting_existing_case_id_without_mutation(
    feedback_report, tmp_path: Path
) -> None:
    _, report = feedback_report
    source = only_mapping(report)
    repo = repository(tmp_path / "repo")
    incoming = propose_cases(
        source, load_suite(feedback_cases=tmp_path / "absent-feedback.jsonl").cases
    ).cases[0]
    reviewed = incoming.model_copy(
        update={"expected": {**incoming.expected, "failure_mode": "FM-08"}}
    )
    assert reviewed.expected != incoming.expected
    (repo / FEEDBACK).write_text(reviewed.model_dump_json() + "\n")
    before = repository_contents(repo)
    response = invoke(source, repo)
    assert response.exit_code == 2, response.output
    assert "Conflicting existing case ID" in response.output
    assert repository_contents(repo) == before
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True
        ).stdout.strip()
        == "main"
    )


@pytest.mark.parametrize(
    "destination",
    [
        "dangling_artifact",
        "artifact_parent",
        "dangling_artifact_parent",
        "feedback_manifest",
        "dangling_feedback_manifest",
        "original_manifest",
        "manifest_parent",
    ],
)
def test_public_command_rejects_symlink_destinations_without_mutation(
    feedback_report, tmp_path: Path, destination: str
) -> None:
    _, report = feedback_report
    source = only_mapping(report)
    repo = repository(tmp_path / "repo")
    digest = report_digest(source)[:12]
    outside = tmp_path / "outside"
    outside.mkdir()
    if destination == "dangling_artifact":
        link = repo / "docs/iteration-4/proposals" / digest / "proposal.json"
        target = outside / "missing.json"
    elif destination.endswith("artifact_parent"):
        link = repo / "docs/iteration-4/proposals"
        target = outside / "missing" if destination.startswith("dangling") else outside
    elif destination == "manifest_parent":
        link = (repo / MANIFEST).parent
        target = outside / "metadata"
        target.mkdir()
        (target / MANIFEST.name).write_bytes((repo / MANIFEST).read_bytes())
        (repo / MANIFEST).unlink()
        link.rmdir()
    else:
        link = repo / (MANIFEST if destination == "original_manifest" else FEEDBACK)
        target = outside / "manifest.jsonl"
        if not destination.startswith("dangling"):
            if destination == "original_manifest":
                target.write_bytes((repo / MANIFEST).read_bytes())
            else:
                retained = propose_cases(
                    source, load_suite(feedback_cases=tmp_path / "absent-feedback.jsonl").cases
                ).cases[0]
                target.write_text(retained.model_dump_json() + "\n")
        if link.exists():
            link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    before = repository_contents(repo)
    outside_before = repository_contents(outside)
    response = invoke(source, repo)
    assert response.exit_code == 2, response.output
    assert "symlink" in response.output.lower()
    assert repository_contents(repo) == before
    assert repository_contents(outside) == outside_before
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True
        ).stdout.strip()
        == "main"
    )
