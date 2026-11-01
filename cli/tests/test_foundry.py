"""Foundry is faked at the SDK boundary; these tests never authenticate or call a model."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from csai import foundry


def publication(*, scores=None, tool_calls=None, tool_definitions=None):
    return foundry.Publication(
        suite="rca",
        metadata={
            "started_at": "2026-10-30T12:00:00+00:00",
            "revision": "revision",
            "agent_version": "1",
            "skill_version": "1",
            "dataset_version": "digest",
            "source": "synthetic",
        },
        rows=[
            foundry.PublishedRow(
                case_id="case-1",
                repeat=1,
                split="train",
                category="clean",
                cohort="regression",
                query="M-0001: synthetic incident",
                response="synthetic answer",
                ground_truth={"failure_mode_id": "FM-01"},
                tool_calls=tool_calls or [],
                tool_definitions=tool_definitions or [],
                scores={"hit_at_1": 1.0} if scores is None else scores,
                gated=True,
            )
        ],
    )


def fake_boundary(monkeypatch, *, status="completed", errored=0, existing=None):
    calls = []

    def create_evaluator(**kwargs):
        calls.append(("evaluator", kwargs))
        return SimpleNamespace(version="1")

    def create_evaluation(**kwargs):
        calls.append(("evaluation", kwargs))
        return SimpleNamespace(id="eval-id")

    def create_run(**kwargs):
        calls.append(("run", kwargs))
        return SimpleNamespace(
            id="run-id",
            status=status,
            result_counts=SimpleNamespace(errored=errored),
            error=None,
            report_url="https://example.test/report",
        )

    client = SimpleNamespace(
        evals=SimpleNamespace(
            list=lambda: existing or [],
            create=create_evaluation,
            runs=SimpleNamespace(create=create_run),
        )
    )
    project = SimpleNamespace(
        beta=SimpleNamespace(evaluators=SimpleNamespace(create_version=create_evaluator)),
        get_openai_client=lambda: nullcontext(client),
    )
    monkeypatch.setattr(foundry, "DefaultAzureCredential", lambda: nullcontext(object()))
    monkeypatch.setattr(foundry, "AIProjectClient", lambda *args: nullcontext(project))
    return calls


def test_published_rows_preserve_scores_truth_and_metadata(monkeypatch):
    saved = publication(scores={"hit_at_1": 1.0, "valid_refs": 0.875})
    before = saved.model_dump_json()
    calls = fake_boundary(monkeypatch)
    assert foundry.publish(saved, endpoint="unused", model="judge") == "https://example.test/report"
    payload = next(value for name, value in calls if name == "run")
    assert payload["metadata"] == saved.metadata
    row = payload["data_source"]["source"]["content"][0]["item"]
    assert row["scores"] == saved.rows[0].scores
    assert row["ground_truth"] == {"failure_mode_id": "FM-01"}
    assert row["source"] == "synthetic"
    assert row["cohort"] == "regression"
    assert saved.model_dump_json() == before
    criteria = next(value for name, value in calls if name == "evaluation")["testing_criteria"]
    assert {criterion["name"] for criterion in criteria} == {
        "code_hit_at_1",
        "code_valid_refs",
        *foundry.BUILTIN_EVALUATORS,
    }


def test_code_mirror_does_not_invent_an_inapplicable_score():
    namespace = {}
    exec(foundry.mirror_code("decisive_ref_recall"), namespace)
    grade = namespace["grade"]
    assert grade({}, {"scores": {"decisive_ref_recall": 0.625}}) == 0.625
    with pytest.raises(KeyError):
        grade({}, {"scores": {}})


def test_sparse_metrics_remain_in_rows_without_false_zero_grades():
    recorded = publication(scores={"hit_at_1": 1.0, "decisive_ref_recall": 0.75})
    recorded.rows.append(
        recorded.rows[0].model_copy(update={"case_id": "case-2", "scores": {"hit_at_1": 0.0}})
    )
    assert recorded.metric_names == ("hit_at_1",)
    assert recorded.items() == [{"item": row.model_dump(mode="json")} for row in recorded.rows]
    assert recorded.rows[0].scores["decisive_ref_recall"] == 0.75
    assert "decisive_ref_recall" not in recorded.rows[1].scores


def test_plumbing_rows_cannot_distort_the_mirrored_quality_denominator():
    recorded = publication()
    recorded.rows.append(
        recorded.rows[0].model_copy(
            update={"case_id": "failed", "failure": {"kind": "plumbing", "code": "timeout"}}
        )
    )
    assert recorded.metric_names == ()
    assert recorded.rows[0].scores == {"hit_at_1": 1.0}


def test_tool_accuracy_maps_real_calls_and_pinned_definitions(monkeypatch):
    calls = [
        {"type": "tool_call", "name": "get_machine_context", "arguments": {"machine_id": "M-0001"}}
    ]
    definitions = [{"type": "function", "name": "get_machine_context", "parameters": {}}]
    recorded = publication(tool_calls=calls, tool_definitions=definitions)
    sdk_calls = fake_boundary(monkeypatch)
    foundry.publish(recorded, endpoint="unused", model="judge")
    payload = next(value for name, value in sdk_calls if name == "run")
    row = payload["data_source"]["source"]["content"][0]["item"]
    assert row["tool_calls"] == calls
    assert row["tool_definitions"] == definitions
    criteria = next(value for name, value in sdk_calls if name == "evaluation")["testing_criteria"]
    accuracy = next(item for item in criteria if item["name"] == "tool_call_accuracy")
    assert accuracy["data_mapping"]["tool_definitions"] == "{{item.tool_definitions}}"


def test_reuses_suite_evaluation_and_keeps_independent_run_metadata(monkeypatch):
    recorded = publication()
    calls = fake_boundary(
        monkeypatch,
        existing=[
            SimpleNamespace(
                id="existing-eval",
                metadata={
                    "csai_suite": "rca",
                    "definition_key": recorded.definition_key,
                    "judge_model": "judge",
                },
            )
        ],
    )
    foundry.publish(recorded, endpoint="unused", model="judge")
    assert [name for name, _ in calls] == ["run"]
    assert calls[0][1]["eval_id"] == "existing-eval"


def test_changed_schema_does_not_create_duplicate_suite_evaluation(monkeypatch):
    calls = fake_boundary(
        monkeypatch,
        existing=[SimpleNamespace(id="existing-eval", metadata={"csai_suite": "rca"})],
    )
    with pytest.raises(foundry.FoundryEvalError, match="schema differs"):
        foundry.publish(publication(), endpoint="unused", model="judge")
    assert not calls


@pytest.mark.parametrize(("status", "errored"), [("failed", 0), ("completed", 1), ("cancelled", 0)])
def test_service_and_item_failures_are_not_reported_as_success(monkeypatch, status, errored):
    fake_boundary(monkeypatch, status=status, errored=errored)
    with pytest.raises(foundry.FoundryEvalError, match="Foundry evaluation"):
        foundry.publish(publication(), endpoint="unused", model="judge")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.01])
def test_invalid_scores_fail_before_authentication(value):
    with pytest.raises(foundry.FoundryEvalError, match=r"\[0, 1\]"):
        foundry.publish(publication(scores={"score": value}), endpoint="unused", model="judge")


def test_missing_tool_definitions_are_not_reconstructed():
    with pytest.raises(foundry.FoundryEvalError, match="not captured"):
        foundry.publish(
            publication(tool_calls=[{"name": "get_machine_context"}]),
            endpoint="unused",
            model="judge",
        )
