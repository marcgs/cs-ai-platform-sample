"""Evaluation suite for the RCA agent."""

from importlib import resources
from pathlib import Path

from cs_platform.evals import EvalSuite
from rca_evals.evaluators import evidence_grounded, outcome, tool_coverage

__all__ = ["load_suite"]


def load_suite() -> EvalSuite:
    data = Path(str(resources.files("rca_evals")))
    return EvalSuite.from_files(
        "rca",
        cases=data / "cases.jsonl",
        thresholds=data / "thresholds.yaml",
        evaluators=(outcome, evidence_grounded, tool_coverage),
    )
