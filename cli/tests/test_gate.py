from pathlib import Path

from csai.gate import (
    THRESHOLDS,
    Row,
    Score,
    Thresholds,
    evaluate_gate,
    merge_runs,
    rows_from_output_items,
)

GATE = Thresholds(
    minimums={"hit_at_1_lenient": 0.7, "decisive_evidence_recall": 0.65},
    hard_checks=frozenset({"injection_resisted"}),
)


def row(case_id: str, cohort: str = "original", repeat: int = 1, **scores: float | None) -> Row:
    return Row(
        case_id,
        repeat,
        cohort,
        {
            name: Score(value, "completed" if value is not None else "error")
            for name, value in scores.items()
        },
    )


def test_means_cover_only_rows_a_metric_applies_to() -> None:
    result = evaluate_gate(
        [
            row("SC-001", hit_at_1_lenient=1.0, decisive_evidence_recall=0.5),
            row("SC-002", hit_at_1_lenient=1.0),
            row("SC-035", "challenge", hit_at_1_lenient=1.0, injection_resisted=1.0),
        ],
        GATE,
    )
    hit, recall = result.metrics
    assert (hit.mean, hit.count) == (1.0, 3)
    assert (recall.mean, recall.count) == (0.5, 1)
    assert result.failures() == ["decisive_evidence_recall: 0.50 < 0.65"]


def test_one_failed_injection_case_fails_the_gate() -> None:
    rows = [row(f"SC-{n:03}", hit_at_1_lenient=1.0, decisive_evidence_recall=1.0) for n in range(9)]
    rows += [row("SC-035", injection_resisted=1.0), row("SC-036", injection_resisted=0.0)]
    result = evaluate_gate(rows, GATE)
    assert result.hard_check_failures == {"injection_resisted": ["SC-036/repeat-1"]}
    assert result.failures() == ["injection_resisted: hard check failed: SC-036/repeat-1"]


def test_feedback_rows_are_report_only() -> None:
    result = evaluate_gate(
        [
            row("SC-001", hit_at_1_lenient=1.0, decisive_evidence_recall=1.0),
            row("SC-035", injection_resisted=1.0),
            row("FB-1", "feedback", hit_at_1_lenient=0.0, injection_resisted=0.0),
        ],
        GATE,
    )
    assert result.report_only == 1
    assert result.failures() == []


def test_evaluator_errors_and_missing_metrics_fail_instead_of_being_skipped() -> None:
    result = evaluate_gate(
        [row("SC-001", hit_at_1_lenient=None, decisive_evidence_recall=1.0)], GATE
    )
    assert result.failures() == [
        "hit_at_1_lenient: evaluator error on SC-001/repeat-1 (error)",
        "hit_at_1_lenient: not evaluated (no applicable rows)",
        "injection_resisted: hard check not evaluated (no applicable rows)",
    ]


def test_skipped_results_do_not_apply() -> None:
    skipped = Row("SC-001", 1, "original", {"decisive_evidence_recall": Score(None, "skipped")})
    result = evaluate_gate([skipped, row("SC-002", decisive_evidence_recall=1.0)], GATE)
    assert result.metrics[1].count == 1


def test_rows_are_read_from_foundry_output_items() -> None:
    item = {
        "datasource_item": {"item": {"case_id": "SC-035", "cohort": "challenge", "repeat": 2}},
        "results": [
            {"name": "injection_resisted", "score": 1, "status": "completed"},
            {"name": "coherence", "score": None, "status": "error"},
        ],
    }
    (parsed,) = rows_from_output_items([item])
    assert parsed.label == "SC-035/repeat-2"
    assert parsed.cohort == "challenge"
    assert parsed.scores["injection_resisted"] == Score(1.0, "completed")
    assert parsed.scores["coherence"] == Score(None, "error")


def test_a_metric_scored_in_two_runs_is_an_error() -> None:
    rows, errors = merge_runs(
        {
            "dense": [row("SC-001", hit_at_1_lenient=1.0)],
            "again": [row("SC-001", hit_at_1_lenient=1.0)],
        }
    )
    assert len(rows) == 2
    assert errors == ["hit_at_1_lenient: scored in both dense and again"]


def test_the_shipped_thresholds_load() -> None:
    config = Thresholds.load(Path(__file__).parents[2] / THRESHOLDS)
    assert set(config.minimums) == {
        "hit_at_1_lenient",
        "decisive_evidence_recall",
        "evidence_grounded",
    }
    assert config.hard_checks == {"injection_resisted"}
