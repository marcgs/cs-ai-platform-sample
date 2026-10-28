from typing import TYPE_CHECKING

from cs_platform.evals import EvalCase, EvalSuite, RunOutput, SuiteResult, Thresholds, run_suite

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
    assert failed.scores == {"exact": 0.0}
    assert result.metrics == {"exact": 0.5}
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
