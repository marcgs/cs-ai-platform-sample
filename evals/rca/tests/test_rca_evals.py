import pytest

from cs_platform.evals import CaseResult, EvalCase, RunOutput, SuiteResult, run_suite, score
from cs_platform.evidence import Evidence
from diagnostics_domain.dataset import load_seed
from diagnostics_mcp.tools import TOOL_NAMES
from rca_agent.report import Hypothesis, RcaReport
from rca_evals import load_suite
from rca_evals.evaluators import (
    calibration,
    data_quality_disclosed,
    decisive_evidence_recall,
    evidence_grounded,
    hit_at_1_lenient,
    injection_resisted,
    knowledge_search,
    outcome,
    ref_exists,
    ruled_out_correctly,
    tool_coverage,
)
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
    assert render(list(suite.cases)) == render(cases_from_seed(load_seed(), previous=suite.cases))
    assert len(suite.cases) == len(load_seed().scenarios)


def test_thresholds_gate_the_metrics_the_evaluators_produce() -> None:
    suite = load_suite()
    produced = {
        **outcome(CASE, output(hypothesis(1, "FM-01", "EC-2101"))),
        **evidence_grounded(CASE, output(hypothesis(1, "FM-01", "EC-2101"))),
        **tool_coverage(CASE, RunOutput()),
        **knowledge_search(CASE, RunOutput()),
    }
    assert set(suite.thresholds.minimums) <= set(produced)


def test_manifest_preserves_persisted_machine_splits_on_extension() -> None:
    dataset = load_seed()
    before = cases_from_seed(dataset)
    added = dataset.scenarios[0].model_copy(update={"id": "SC-999", "machine_id": "M-9999"})
    after = cases_from_seed(
        dataset.model_copy(update={"scenarios": (*dataset.scenarios, added)}),
        previous=before,
    )
    assert {case.id: case.split for case in before} == {
        case.id: case.split for case in after if case.id != added.id
    }
    for category in {case.truth.category for case in before if case.truth}:
        splits = {case.split for case in before if case.truth and case.truth.category == category}
        assert splits == {"train", "test"}


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


@pytest.mark.parametrize("name", ["azure_ai_search", "diagnostics___azure_ai_search"])
def test_search_without_citations_is_not_used_knowledge(name: str) -> None:
    result = output(hypothesis(1, "FM-01", "EC-2101"))
    result.tool_calls = [name, name]
    assert knowledge_search(CASE, result) == {"knowledge_search_called": 1.0}
    assert outcome(CASE, result)["used_knowledge"] == 0.0
    assert knowledge_search(CASE, RunOutput(tool_calls=["get_logbook"])) == {
        "knowledge_search_called": 0.0
    }


def test_fabricated_history_is_used_but_not_grounded() -> None:
    result = output(hypothesis(1, "FM-01", "HC-invented"))
    assert outcome(CASE, result)["used_knowledge"] == 1.0
    assert evidence_grounded(CASE, result) == {"evidence_grounded": 0.0}
    assert knowledge_search(CASE, result) == {"knowledge_search_called": 0.0}


@pytest.mark.parametrize(("citing_reports", "passes"), [(13, True), (12, False)])
def test_measured_knowledge_gate_allows_one_case_below_the_observed_minimum(
    citing_reports: int, passes: bool
) -> None:
    suite = load_suite()
    dataset = load_seed()
    results = []
    for index, case in enumerate(suite.cases):
        if case.truth and case.truth.category != "clean":
            continue
        history = next(
            item
            for item in dataset.historical_cases
            if item.confirmed_failure_mode == case.expected["failure_mode"]
        )
        observed = output(
            hypothesis(
                1,
                case.expected["failure_mode"],
                history.id if index < citing_reports else "EC-2101",
            ),
            machine_id=case.expected["machine_id"],
        )
        observed.tool_calls = [*TOOL_NAMES, "azure_ai_search"]
        results.append(
            CaseResult(case_id=case.id, scores=score(suite, case, observed), output=observed)
        )
    failures = SuiteResult(suite=suite.name, cases=results).failures(suite.thresholds)
    assert (not failures) == passes
    if not passes:
        assert len(failures) == 1
        assert failures[0].startswith("used_knowledge:")


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


def _challenge_case(category: str, variant: int = 0) -> EvalCase:
    return [
        case
        for case in cases_from_seed(load_seed())
        if case.truth and case.truth.category == category
    ][variant]


def _truthful_output(case: EvalCase) -> RunOutput:
    assert case.truth
    missing_identity = case.truth.category == "missing_machine"
    result = output(
        hypothesis(1, case.expected["failure_mode"], *case.truth.decisive_refs),
        machine_id="unknown" if missing_identity else case.expected["machine_id"],
    )
    assert isinstance(result.value, RcaReport)
    result.value.missing_information = [
        "Machine identifier and incident timestamp required."
        if missing_identity
        else "No physical fault reproduced; healthy checks require validation."
        if case.truth.category == "no_fault_found"
        else "No catalog signature matches; collect more evidence."
        if case.truth.category == "out_of_catalog"
        else "Telemetry collection gap; duplicate timestamps, late arrivals and clock skew "
        "must be repaired. The primary sensor is stuck or drifting and disagrees with the gauge."
    ]
    return result


@pytest.mark.parametrize(
    "category",
    [
        "clean",
        "overlapping",
        "no_fault_found",
        "out_of_catalog",
        "missing_machine",
        "injection",
        "sensor_fault",
        "data_gap",
        "nuisance_alarm",
    ],
)
def test_ground_truth_metrics_accept_sound_and_reject_wrong_reports(category: str) -> None:
    case = _challenge_case(category)
    assert case.truth
    good = _truthful_output(case)
    assert hit_at_1_lenient(case, good) == {"hit_at_1_lenient": 1.0}
    bad = output(hypothesis(1, "FM-08", "EC-2104"), machine_id=case.expected["machine_id"])
    if case.expected["failure_mode"] == "FM-08":
        bad = output(hypothesis(1, "FM-01", "EC-2104"), machine_id=case.expected["machine_id"])
    assert hit_at_1_lenient(case, bad) == {"hit_at_1_lenient": 0.0}
    if case.truth.decisive_refs:
        assert decisive_evidence_recall(case, good) == {"decisive_evidence_recall": 1.0}
        assert decisive_evidence_recall(case, bad) == {"decisive_evidence_recall": 0.0}
    if case.truth.ruled_out_failure_modes:
        wrong = output(
            hypothesis(1, case.truth.ruled_out_failure_modes[0]),
            machine_id=case.expected["machine_id"],
        )
        assert ruled_out_correctly(case, good) == {"ruled_out_correctly": 1.0}
        assert ruled_out_correctly(case, wrong) == {"ruled_out_correctly": 0.0}
    assert score(load_suite(), case, good) == score(load_suite(), case, good)


def test_decisive_recall_is_not_generic_grounding_and_lenient_accepts_declared_alternative() -> (
    None
):
    case = _challenge_case("overlapping")
    assert case.truth
    case = case.model_copy(
        update={"truth": case.truth.model_copy(update={"acceptable_failure_modes": ("FM-08",)})}
    )
    assert case.truth
    observed = output(hypothesis(1, "FM-08", case.truth.decisive_refs[0]))
    assert hit_at_1_lenient(case, observed) == {"hit_at_1_lenient": 1.0}
    assert outcome(case, observed)["hit_at_1"] == 0.0
    assert decisive_evidence_recall(case, observed) == {"decisive_evidence_recall": 0.5}


def test_missing_identity_requires_abstention_not_a_lucky_guess() -> None:
    case = _challenge_case("missing_machine")
    good = _truthful_output(case)
    assert outcome(case, good)["schema_valid"] == 1.0
    assert outcome(case, good)["hit_at_1"] == 1.0
    assert isinstance(good.value, RcaReport)
    good.value.machine_id = case.expected["machine_id"]
    assert outcome(case, good)["schema_valid"] == 0.0
    assert outcome(case, good)["hit_at_1"] == 0.0
    assert hit_at_1_lenient(case, good) == {"hit_at_1_lenient": 0.0}
    good.value.machine_id = "unknown"
    good.value.hypotheses[0].confidence = 0.99
    assert hit_at_1_lenient(case, good) == {"hit_at_1_lenient": 0.0}
    good.value.hypotheses[0].confidence = 0.5
    good.value.missing_information = ["The machine is healthy."]
    assert hit_at_1_lenient(case, good) == {"hit_at_1_lenient": 0.0}


@pytest.mark.parametrize("category", ["no_fault_found", "out_of_catalog"])
@pytest.mark.parametrize("missing", [[], [""], [" "]])
def test_unknown_without_reason_is_not_a_sound_abstention(
    category: str, missing: list[str]
) -> None:
    case = _challenge_case(category)
    observed = _truthful_output(case)
    assert isinstance(observed.value, RcaReport)
    observed.value.missing_information = missing
    assert hit_at_1_lenient(case, observed) == {"hit_at_1_lenient": 0.0}


def test_injection_scoring_rejects_echoed_and_followed_instructions() -> None:
    case = _challenge_case("injection")
    good = _truthful_output(case)
    assert injection_resisted(case, good) == {"injection_resisted": 1.0}
    assert isinstance(good.value, RcaReport)
    assert case.truth
    good.value.summary = case.truth.injection_markers[0].lower()
    assert injection_resisted(case, good) == {"injection_resisted": 0.0}
    good.value.summary = "..."
    good.value.hypotheses[0].failure_mode_id = "FM-08"
    good.value.hypotheses[0].confidence = 1.0
    assert injection_resisted(case, good) == {"injection_resisted": 0.0}


@pytest.mark.parametrize("category", ["data_gap", "sensor_fault"])
@pytest.mark.parametrize("variant", range(4))
def test_quality_requires_actual_anomaly_disclosure(category: str, variant: int) -> None:
    case = _challenge_case(category, variant)
    assert data_quality_disclosed(case, _truthful_output(case)) == {"data_quality_disclosed": 1.0}
    wrong = output(hypothesis(1, case.expected["failure_mode"]))
    assert data_quality_disclosed(case, wrong) == {"data_quality_disclosed": 0.0}
    assert isinstance(wrong.value, RcaReport)
    wrong.value.missing_information = ["More data needed."]
    assert data_quality_disclosed(case, wrong) == {"data_quality_disclosed": 0.0}


def test_nonapplicable_metrics_are_sparse_and_calibration_is_brier_loss() -> None:
    clean = _challenge_case("clean")
    observed = _truthful_output(clean)
    assert injection_resisted(clean, observed) == {}
    assert data_quality_disclosed(clean, observed) == {}
    assert ruled_out_correctly(clean, observed) == {}
    assert decisive_evidence_recall(_challenge_case("missing_machine"), observed) == {}
    assert calibration(CASE, observed) == {}
    assert isinstance(observed.value, RcaReport)
    observed.value.hypotheses[0].confidence = 0.9
    assert calibration(clean, observed)["calibration"] == pytest.approx(0.01)
    observed.value.hypotheses[0].failure_mode_id = "unknown"
    assert calibration(clean, observed)["calibration"] == pytest.approx(0.81)


async def test_new_categories_are_report_only_and_do_not_weaken_original_gate() -> None:
    suite = load_suite()

    async def target(case: EvalCase) -> RunOutput:
        if not case.truth or case.truth.category != "clean":
            return RunOutput(error="TimeoutError: synthetic challenge failure")
        observed = _truthful_output(case)
        assert isinstance(observed.value, RcaReport)
        observed.value.hypotheses[0].evidence.append(
            Evidence(source="test", ref="HC-0001", excerpt="...")
        )
        observed.tool_calls = list(TOOL_NAMES)
        return observed

    result = await run_suite(suite, target, retries=0)
    assert len(result.cases) == 50
    assert sum(case.gated for case in result.cases) == 18
    assert not result.failures(suite.thresholds)
    assert result.gate_metrics["hit_at_1"] == 1.0
    assert "injection_resisted" not in result.metrics
