from math import nextafter
from typing import TYPE_CHECKING

import pytest

from cs_platform.evals import (
    CaseResult,
    EvalCase,
    EvalSuite,
    EvalTruth,
    RunOutput,
    SuiteResult,
    Thresholds,
    assign_splits,
    bootstrap_intervals,
    classify_error,
    paired_difference_intervals,
    run_suite,
    score,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def exact_match(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
    return {"exact": float(output.text == case.expected["answer"])}


def suite(*answers: str, minimum: float = 0.5) -> EvalSuite:
    cases = tuple(
        EvalCase(id=f"C-{i}", input=f"question {i}", expected={"answer": answer})
        for i, answer in enumerate(answers)
    )
    return EvalSuite("demo", cases, Thresholds(minimums={"exact": minimum}), (exact_match,))


async def test_scores_every_case_and_averages_metrics() -> None:
    async def target(case: EvalCase) -> RunOutput:
        return RunOutput(text="yes")

    seen: list[str] = []
    result = await run_suite(suite("yes", "no"), target, on_result=lambda r: seen.append(r.case_id))

    assert sorted(seen) == ["C-0", "C-1"]
    assert [c.scores for c in result.cases] == [{"exact": 1.0}, {"exact": 0.0}]
    assert result.metrics == {"exact": 0.5}
    assert result.failures(Thresholds(minimums={"exact": 0.5})) == []
    assert result.failures(Thresholds(minimums={"exact": 0.75})) == ["exact: 0.50 < 0.75"]


async def test_target_errors_are_recorded_and_scored() -> None:
    async def target(case: EvalCase) -> RunOutput:
        if case.id == "C-1":
            raise TimeoutError("agent didn't answer")
        return RunOutput(text="yes")

    result = await run_suite(suite("yes", "yes"), target, retries=1, backoff_s=0)

    failed = result.cases[1]
    assert failed.output.error == "TimeoutError: agent didn't answer"
    assert failed.output.attempts == 2
    assert failed.scores == {}
    assert failed.output.failure is not None
    assert failed.output.failure.code == "timeout"
    assert result.metrics == {"exact": 1.0}
    assert result.errored == ["C-1"]
    assert result.failures(Thresholds(minimums={}))[0] == "1 case(s) errored: C-1"


async def test_transient_errors_are_retried() -> None:
    calls = 0

    async def target(case: EvalCase) -> RunOutput:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("rate limited")
        return RunOutput(text="yes")

    result = await run_suite(suite("yes"), target, retries=2, backoff_s=0)

    assert result.cases[0].output.error is None
    assert result.cases[0].output.attempts == 2
    assert result.errored == []


def test_missing_metric_counts_as_failure() -> None:
    result = SuiteResult(suite="demo", cases=[])
    assert result.failures(Thresholds(minimums={"exact": 0.1})) == ["exact: 0.00 < 0.10"]


@pytest.mark.parametrize(
    ("scores", "passes"),
    [
        ([0.8] * 9 + [1.0] * 9, True),
        ([1.0] * 9 + [0.8] * 9, True),
        ([1.0, 0.8] * 8 + [0.8, 0.8], False),
        ([nextafter(0.9, 0.0)] * 18, False),
    ],
)
def test_mean_preserves_exact_boundary_without_tolerating_lower_scores(
    scores: list[float], passes: bool
) -> None:
    result = SuiteResult(
        suite="demo",
        cases=[
            CaseResult(case_id=f"C-{i}", scores={"coverage": value}, output=RunOutput())
            for i, value in enumerate(scores)
        ],
    )
    if passes:
        assert result.metrics["coverage"] == 0.9
    assert (not result.failures(Thresholds(minimums={"coverage": 0.9}))) == passes


def test_suite_loads_from_files(tmp_path: Path) -> None:
    (tmp_path / "cases.jsonl").write_text(
        '{"id": "C-0", "input": "q", "expected": {"answer": "a"}}\n\n', encoding="utf-8"
    )
    (tmp_path / "thresholds.yaml").write_text("minimums:\n  exact: 0.9\n", encoding="utf-8")

    loaded = EvalSuite.from_files(
        "demo", tmp_path / "cases.jsonl", tmp_path / "thresholds.yaml", (exact_match,)
    )

    assert [c.id for c in loaded.cases] == ["C-0"]
    assert loaded.thresholds.minimums == {"exact": 0.9}


async def test_repeats_are_not_retries_and_bootstrap_nests_them() -> None:
    calls = 0

    async def target(case: EvalCase) -> RunOutput:
        nonlocal calls
        calls += 1
        return RunOutput(text="yes" if calls % 2 else "no")

    result = await run_suite(suite("yes", "yes"), target, repeats=3, concurrency=1)
    assert calls == 6
    assert [case.repeat for case in result.cases] == [1, 2, 3, 1, 2, 3]
    assert result.metrics == {"exact": 0.5}
    assert result.intervals == result.intervals
    low, high = result.intervals["exact"]
    assert low < 0.5 < high
    assert all(case.output.attempts == 1 for case in result.cases)
    assert score(suite("yes"), suite("yes").cases[0], RunOutput(text="yes")) == {"exact": 1}


def test_case_bootstrap_does_not_treat_repeats_as_independent_cases() -> None:
    cases = [
        CaseResult(case_id=identity, repeat=repeat, scores={"exact": value}, output=RunOutput())
        for identity, value in (("A", 0.0), ("B", 1.0))
        for repeat in range(10)
    ]
    assert bootstrap_intervals(cases)["exact"] == (0.0, 1.0)


def test_paired_difference_ci_and_mismatched_cohorts() -> None:
    def result(value: float) -> SuiteResult:
        return SuiteResult(
            suite="demo",
            cases=[CaseResult(case_id="A", scores={"exact": value}, output=RunOutput(text="yes"))],
        )

    assert paired_difference_intervals(result(0), result(1)) == {"exact": (1.0, 1.0)}
    with pytest.raises(ValueError, match="identical"):
        paired_difference_intervals(result(0), SuiteResult(suite="demo", cases=[]))


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("RateLimitError: 429", "rate_limit"),
        ("TimeoutError: expired", "timeout"),
        ("ConnectionError: lost", "transport"),
        ("incomplete: max_output_tokens", "truncated_output"),
    ],
)
def test_structured_plumbing_classification(error: str, code: str) -> None:
    failure = classify_error(RunOutput(error=error))
    assert failure is not None
    assert (failure.kind, failure.code) == ("plumbing", code)
    assert classify_error(RunOutput()).code == "missing_output"  # type: ignore[union-attr]


async def test_only_explicit_regression_cohort_is_gated() -> None:
    base = suite("yes", "no", "no")
    cases = (
        base.cases[0],
        base.cases[1].model_copy(update={"truth": EvalTruth(category="overlapping")}),
        base.cases[2].model_copy(update={"truth": EvalTruth(category="clean")}),
    )
    extended = EvalSuite(
        base.name, cases, base.thresholds, base.evaluators, gate_case_ids=frozenset({"C-0"})
    )

    async def target(case: EvalCase) -> RunOutput:
        if case.id == "C-1":
            raise TimeoutError
        return RunOutput(text="yes")

    result = await run_suite(extended, target, repeats=2, retries=0)
    assert result.gate_metrics == {"exact": 1.0}
    assert result.metrics == {"exact": 0.5}
    assert result.failures(base.thresholds) == []
    assert result.groups["category"]["clean"]["exact"] == 0.5
    assert result.groups["category"]["overlapping"] == {}
    assert any("saturated" in warning for warning in result.warnings(base.thresholds))


def test_split_hash_is_machine_grouped_order_and_append_stable() -> None:
    cases = tuple(
        EvalCase(
            id=f"case-{index}",
            input="q",
            expected={"machine_id": f"M-{index:04d}"},
            truth=EvalTruth(category="overlapping" if index % 2 else "clean"),
        )
        for index in range(1, 101)
    )
    assigned = assign_splits(cases)
    mapping = {case.id: case.split for case in assigned}
    assert mapping == {case.id: case.split for case in assign_splits(tuple(reversed(cases)))}
    appended = assign_splits((*assigned[:1], *cases[1:]))
    assert mapping["case-1"] == appended[0].split
    for category in ("clean", "overlapping"):
        train = sum(
            case.split == "train"
            for case in assigned
            if case.truth is not None and case.truth.category == category
        )
        assert 20 < train < 45
    duplicate = cases[0].model_copy(
        update={"id": "other", "truth": EvalTruth(category="injection")}
    )
    assert assign_splits((*assigned, duplicate))[-1].split == assigned[0].split
    with pytest.raises(ValueError, match="both splits"):
        assign_splits(
            (
                cases[0].model_copy(update={"split": "train"}),
                duplicate.model_copy(update={"split": "test"}),
            )
        )


def test_small_category_strata_have_held_out_machines() -> None:
    cases = tuple(
        EvalCase(
            id=f"case-{index}",
            input="q",
            expected={"machine_id": f"M-{index:04d}"},
            truth=EvalTruth(category="missing_machine"),
        )
        for index in range(4)
    )
    assigned = assign_splits(cases)
    assert sum(case.split == "train" for case in assigned) == 3
    assert sum(case.split == "test" for case in assigned) == 1
    appended = assign_splits(
        (
            *assigned,
            EvalCase(
                id="new",
                input="q",
                expected={"machine_id": "M-0100"},
                truth=EvalTruth(category="missing_machine"),
            ),
        )
    )
    assert [case.split for case in appended[:4]] == [case.split for case in assigned]


async def test_sparse_metrics_are_not_penalized_and_unparseable_is_not_plumbing() -> None:
    from cs_platform.evals import RunError

    def sparse(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
        return {"sparse": 0.8} if case.id == "C-0" else {}

    base = suite("yes", "yes")
    extended = EvalSuite(base.name, base.cases, base.thresholds, (*base.evaluators, sparse))

    async def target(case: EvalCase) -> RunOutput:
        return RunOutput(
            text="not JSON", failure=RunError(kind="unparseable", code="invalid_output")
        )

    result = await run_suite(extended, target)
    assert result.metrics == {"exact": 0.0, "sparse": 0.8}
    assert result.errored == ["C-0", "C-1"]
    assert all(case.output.attempts == 1 for case in result.cases)


@pytest.mark.parametrize("hit_at_1", [1.0, 0.0])
async def test_quality_miss_ignores_directionless_informational_metrics(hit_at_1: float) -> None:
    scores = {
        "schema_valid": 1.0,
        "hit_at_1": hit_at_1,
        "hit_at_3": 1.0,
        "tool_coverage": 1.0,
        "evidence_grounded": 1.0,
        "used_knowledge": 1.0,
        "calibration": 0.0,
        "decisive_evidence_recall": 0.5,
    }

    def evaluate(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
        return scores

    async def target(case: EvalCase) -> RunOutput:
        return RunOutput(text="structured report")

    thresholds = Thresholds(
        minimums={
            "schema_valid": 1.0,
            "hit_at_1": 0.8,
            "hit_at_3": 0.9,
            "tool_coverage": 0.9,
            "evidence_grounded": 0.95,
            "used_knowledge": 0.7,
        }
    )
    base = suite("yes")
    result = await run_suite(EvalSuite(base.name, base.cases, thresholds, (evaluate,)), target)
    assert result.cases[0].scores == scores
    failure = result.cases[0].output.failure
    if hit_at_1 == 1.0:
        assert failure is None
        assert result.failures(thresholds) == []
    else:
        assert failure is not None
        assert (failure.kind, failure.code) == ("wrong_answer", "quality_miss")
        assert result.failures(thresholds) == ["hit_at_1: 0.00 < 0.80"]
