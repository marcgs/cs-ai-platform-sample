import pytest

from cs_platform.evals import EvalCase, RunOutput
from cs_platform.evidence import Evidence
from diagnostics_domain.dataset import load_seed
from rca_agent.report import Hypothesis, RcaReport
from rca_evals import load_suite
from rca_evals.evaluators import evidence_grounded, outcome, ref_exists, tool_coverage
from rca_evals.manifest import cases_from_seed, render

CASE = EvalCase(
    id="SC-001",
    input="M-0001: stage temperature alarm",
    expected={"machine_id": "M-0001", "failure_mode": "FM-01"},
)


def hypothesis(rank: int, failure_mode_id: str, *refs: str) -> Hypothesis:
    return Hypothesis(
        rank=rank,
        failure_mode_id=failure_mode_id,
        title=failure_mode_id,
        root_cause="...",
        confidence=0.5,
        evidence=[Evidence(source="test", ref=ref, excerpt="...") for ref in refs],
        recommended_checks=[],
    )


def output(*hypotheses: Hypothesis, machine_id: str = "M-0001") -> RunOutput:
    report = RcaReport(
        machine_id=machine_id, summary="...", hypotheses=list(hypotheses), missing_information=[]
    )
    return RunOutput(value=report)


def test_committed_manifest_matches_the_seed_scenarios() -> None:
    suite = load_suite()
    assert render(list(suite.cases)) == render(cases_from_seed(load_seed()))
    assert len(suite.cases) == len(load_seed().scenarios)


def test_thresholds_gate_the_metrics_the_evaluators_produce() -> None:
    suite = load_suite()
    produced = {
        **outcome(CASE, output(hypothesis(1, "FM-01", "EC-2101"))),
        **evidence_grounded(CASE, output(hypothesis(1, "FM-01", "EC-2101"))),
        **tool_coverage(CASE, RunOutput()),
    }
    assert set(suite.thresholds.minimums) <= set(produced)


def test_expected_failure_mode_ranked_first() -> None:
    scores = outcome(
        CASE, output(hypothesis(1, "FM-01", "EC-2101"), hypothesis(2, "FM-05", "EC-2104"))
    )
    assert scores == {"schema_valid": 1.0, "hit_at_1": 1.0, "hit_at_3": 1.0, "used_knowledge": 0.0}


def test_expected_failure_mode_ranked_second() -> None:
    scores = outcome(
        CASE, output(hypothesis(1, "FM-05", "EC-2104"), hypothesis(2, "FM-01", "EC-2101"))
    )
    assert (scores["hit_at_1"], scores["hit_at_3"]) == (0.0, 1.0)


def test_rank_order_not_list_order_decides() -> None:
    scores = outcome(
        CASE, output(hypothesis(2, "FM-05", "EC-2104"), hypothesis(1, "FM-01", "EC-2101"))
    )
    assert scores["hit_at_1"] == 1.0


@pytest.mark.parametrize(
    "report",
    [
        output(hypothesis(1, "FM-01", "EC-2101"), machine_id="M-0002"),  # wrong machine
        output(hypothesis(1, "FM-01")),  # no evidence
        output(hypothesis(1, "FM-01", "EC-2101"), hypothesis(3, "FM-05", "EC-2104")),  # rank gap
    ],
)
def test_malformed_reports_are_not_schema_valid(report: RunOutput) -> None:
    assert outcome(CASE, report)["schema_valid"] == 0.0


def test_missing_report_scores_zero() -> None:
    error = RunOutput(error="TimeoutError")
    assert set(outcome(CASE, error).values()) == {0.0}
    assert evidence_grounded(CASE, error) == {"evidence_grounded": 0.0}


def test_citing_a_historical_case_counts_as_using_knowledge() -> None:
    assert outcome(CASE, output(hypothesis(1, "FM-01", "HC-0006")))["used_knowledge"] == 1.0


def test_refs_must_exist_and_belong_to_the_machine() -> None:
    dataset = load_seed()
    event = next(e for e in dataset.error_events if e.machine_id == "M-0001")
    other_event = next(e for e in dataset.error_events if e.machine_id != "M-0001")
    entry = next(e for e in dataset.logbook if e.machine_id == "M-0001")

    assert ref_exists(event.id, "M-0001", dataset)
    assert ref_exists(entry.id, "M-0001", dataset)
    assert ref_exists("TS:M-0001:stage_coolant_temp_c", "M-0001", dataset)
    assert ref_exists("EC-2101", "M-0001", dataset)
    assert ref_exists("HC-0006", "M-0001", dataset)

    assert not ref_exists(other_event.id, "M-0001", dataset)
    assert not ref_exists("TS:M-0002:stage_coolant_temp_c", "M-0001", dataset)
    assert not ref_exists("TS:M-0001:made_up_signal", "M-0001", dataset)
    assert not ref_exists("EV-999999", "M-0001", dataset)
    assert not ref_exists("EC-0000", "M-0001", dataset)
    assert not ref_exists("the logbook", "M-0001", dataset)


def test_grounding_is_the_share_of_real_refs() -> None:
    scores = evidence_grounded(CASE, output(hypothesis(1, "FM-01", "EC-2101", "EV-999999")))
    assert scores == {"evidence_grounded": 0.5}


def test_tool_coverage_counts_distinct_diagnostic_tools() -> None:
    calls = [
        "diagnostics___get_machine_context",
        "diagnostics___get_logbook",
        "get_logbook",
        "azure_ai_search",
    ]
    assert tool_coverage(CASE, RunOutput(tool_calls=calls)) == {"tool_coverage": 0.4}
    assert tool_coverage(CASE, RunOutput()) == {"tool_coverage": 0.0}
