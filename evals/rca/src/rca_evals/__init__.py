"""Evaluation suite for the RCA agent."""

from importlib import resources
from pathlib import Path

from cs_platform.evals import EvalSuite
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

__all__ = ["load_suite"]


def load_suite() -> EvalSuite:
    data = Path(str(resources.files("rca_evals")))
    return EvalSuite.from_files(
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
        gate_case_ids=frozenset(f"SC-{number:03d}" for number in range(1, 19)),
    )
