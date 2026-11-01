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
from csai.case_consensus import review_consensus
from csai.case_proposal import CaseProposal
from csai.cases import FEEDBACK, MANIFEST
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback import generate_feedback
from episode_analysis.classifier import CachedClassifier, ClassifierConfig
from episode_analysis.models import EnrichedEpisode, Label, Report, ReviewSummary
from episode_analysis.pipeline import analyze, prepare
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
            "clusters": [
                cluster.model_copy(
                    update={
                        "eval_cases": [candidate.model_copy(deep=True)],
                        "episode_ids": [candidate.episode_id],
                        "frequency": 1,
                    }
                )
            ]
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


@pytest.mark.parametrize(
    ("mutation", "reason", "k4"),
    [
        ("changed_result", "fingerprint", True),
        ("non_replayable", "Incomplete tool capture", True),
        ("explicit_metadata", "non-replayable", True),
        ("truncated_episode", "Incomplete episode capture", True),
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


@pytest.mark.parametrize("kind", ["single", "disagree"])
def test_public_command_waits_or_sends_disagreement_to_expert(
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
    else:
        selected[1] = selected[1].model_copy(
            update={
                "feedback": selected[1].feedback.model_copy(update={"actual_root_cause": "FM-08"})
            }
        )
    weights = {name: metric.reliability for name, metric in report.reviewer_agreement.items()}
    consensus = review_consensus(
        selected,
        episode_id=candidate.episode_id,
        source_review_ids=[row.id for row in selected],
        reviewer_weights=weights,
    )
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
    original = load_suite()
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


@pytest.mark.parametrize(
    "mutation",
    [
        "cluster_key",
        "review_ids",
        "supporting_review_ids",
        "verdict",
        "tool_fingerprints",
        "identity",
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
        }
        case = case.model_copy(
            update={"provenance": provenance.model_copy(update={mutation: updates[mutation]})}
        )
    path = repo / FEEDBACK
    path.write_text(case.model_dump_json() + "\n")
    with pytest.raises(ValueError, match="expected"):
        load_feedback_cases(path, existing=load_suite().cases)
