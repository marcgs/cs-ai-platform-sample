"""A completed Foundry run is not proof that its evaluators executed."""

from .results import JUDGES, Criterion, OutputItem, judge_errors


def test_completed_row_still_reports_per_judge_execution_error() -> None:
    row = OutputItem(
        id="1",
        results=[Criterion(name=name, score=5.0) for name in JUDGES if name != "tool_call_accuracy"]
        + [
            Criterion(
                name="tool_call_accuracy",
                status="error",
                sample={"error": {"message": "The 'arguments' field must be a dictionary"}},
            )
        ],
    )
    errors = judge_errors([row])
    assert len(errors) == 1
    assert "tool_call_accuracy" in errors[0]
    assert "must be a dictionary" in errors[0]


def test_missing_judge_is_not_a_success() -> None:
    assert len(judge_errors([OutputItem(id="1", results=[])])) == len(JUDGES)


def test_low_judge_scores_are_results_not_execution_failures() -> None:
    row = OutputItem(
        id="1",
        results=[
            Criterion(name=name, score=0.0, status="completed", sample=None) for name in JUDGES
        ],
    )
    assert judge_errors([row]) == []
