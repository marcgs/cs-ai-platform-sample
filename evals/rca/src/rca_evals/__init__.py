"""Evaluation suite for the RCA agent."""

from dataclasses import replace
from importlib import resources
from pathlib import Path

from cs_platform.evals import EvalCase, EvalSuite
from rca_evals.evaluators import (
    calibration,
    data_quality_disclosed,
    decisive_evidence_recall,
    evidence_grounded,
    hit_at_1_lenient,
    injection_resisted,
    knowledge_search,
    outcome,
    ruled_out_correctly,
    tool_coverage,
)
from rca_evals.feedback import load_feedback_cases

__all__ = ["load_suite"]


def gate_metric_applicability(case: EvalCase) -> frozenset[str]:
    """Declare outcome denominators from case truth, never from an agent answer."""
    metrics = {"evidence_grounded"}
    if case.truth:
        metrics.add("hit_at_1_lenient")
        if case.truth.decisive_refs:
            metrics.add("decisive_evidence_recall")
        if case.truth.category == "injection" and case.cohort != "feedback":
            metrics.add("injection_resisted")
    return frozenset(metrics)


def load_suite(*, feedback_cases: Path | None = None) -> EvalSuite:
    data = Path(str(resources.files("rca_evals")))
    suite = EvalSuite.from_files(
        "rca",
        cases=data / "cases.jsonl",
        thresholds=data / "thresholds.yaml",
        evaluators=(
            outcome,
            evidence_grounded,
            tool_coverage,
            knowledge_search,
            decisive_evidence_recall,
            ruled_out_correctly,
            hit_at_1_lenient,
            injection_resisted,
            data_quality_disclosed,
            calibration,
        ),
    )
    feedback = load_feedback_cases(
        feedback_cases or data / "feedback_cases.jsonl", existing=suite.cases
    )
    return replace(
        suite,
        cases=(*suite.cases, *feedback),
        gate_case_ids=frozenset(case.id for case in suite.cases),
        original_case_ids=frozenset(f"SC-{number:03d}" for number in range(1, 19)),
        metric_applicability=gate_metric_applicability,
    )
