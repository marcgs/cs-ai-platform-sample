"""Portable grader scores must preserve the local gate's invalid-report semantics."""

import pytest

from cs_platform.evals import RunOutput, score
from rca_agent.report import RcaReport
from rca_evals import load_suite

from .graders import DENSE, code


@pytest.mark.parametrize("machine", ["M-0001", "unknown"])
def test_bundled_metrics_match_local_scores_including_invalid_report(machine: str) -> None:
    suite = load_suite()
    case = next(case for case in suite.cases if case.id == "SC-001")
    ref = case.truth.decisive_refs[0] if case.truth else ""
    report = RcaReport.model_validate(
        {
            "machine_id": machine,
            "summary": "Cooling drift.",
            "hypotheses": [
                {
                    "rank": 1,
                    "failure_mode_id": case.expected["failure_mode"],
                    "title": "Cooling",
                    "root_cause": "Cooling drift",
                    "confidence": 0.8,
                    "evidence": [
                        {"source": "get_telemetry_window", "ref": ref, "excerpt": "Drift"}
                    ],
                    "recommended_checks": [],
                }
            ],
            "missing_information": [],
        }
    )
    names = ["diagnostics___get_machine_context", "azure_ai_search"]
    expected = score(suite, case, RunOutput(value=report, tool_calls=names))
    expected["calibration_score"] = 1 - expected["calibration"]
    item = {
        "expected": case.expected,
        "truth": case.truth.model_dump(mode="json") if case.truth else {},
        "response": report.model_dump_json(),
        "output_items": [{"content": [{"type": "function_call", "name": name}]} for name in names],
        "valid_refs": [ref],
        "causal_note": "",
    }
    for metric in DENSE:
        namespace: dict[str, object] = {"__name__": "foundry_grade"}
        exec(compile(code(metric), "foundry_grade", "exec"), namespace)
        grader = namespace["grade"]
        assert callable(grader)
        assert grader({}, item) == pytest.approx(expected[metric], abs=1e-12)
