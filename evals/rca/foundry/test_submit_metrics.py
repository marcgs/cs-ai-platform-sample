"""Verify applicable-only grading submissions and no ambiguous resubmission."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from . import submit_metrics

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("pending", [False, True])
def test_submission_uses_applicable_rows_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pending: bool
) -> None:
    submissions: list[dict] = []
    criteria: list[dict] = []

    def create_evaluation(*, testing_criteria: list[dict], **_kwargs: object) -> SimpleNamespace:
        criteria.extend(testing_criteria)
        return SimpleNamespace(id="definition")

    def create_run(*, data_source: dict, **_kwargs: object) -> SimpleNamespace:
        submissions.append(data_source)
        return SimpleNamespace(id="run")

    def create_version(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(name="metric", version="1")

    client = SimpleNamespace(
        evals=SimpleNamespace(create=create_evaluation, runs=SimpleNamespace(create=create_run))
    )
    project = SimpleNamespace(
        beta=SimpleNamespace(evaluators=SimpleNamespace(create_version=create_version)),
        get_openai_client=lambda **_kwargs: nullcontext(client),
    )
    monkeypatch.setattr(submit_metrics, "load_environment", lambda: None)
    monkeypatch.setattr(
        submit_metrics.PlatformSettings,
        "from_env",
        lambda: SimpleNamespace(foundry_project_endpoint="endpoint", model_deployment="model"),
    )
    monkeypatch.setattr(submit_metrics, "AzureCliCredential", lambda: nullcontext())
    monkeypatch.setattr(submit_metrics, "AIProjectClient", lambda *_args: nullcontext(project))
    rows = [
        {
            "case_id": category,
            "query": "Synthetic incident",
            "truth": {
                "category": category,
                "decisive_refs": [],
                "ruled_out_failure_modes": [],
            },
        }
        for category in ("clean", "data_gap")
    ]
    dataset = tmp_path / "input.jsonl"
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setattr(
        "sys.argv",
        [
            "submit",
            "--dataset",
            str(dataset),
            "--receipts",
            str(tmp_path / "receipts"),
            "--scope",
            "sparse",
            "--metric",
            "data_quality_disclosed",
        ],
    )
    submit_metrics.main()
    if pending:
        (tmp_path / "receipts/data_quality_disclosed.json").write_text(
            json.dumps({"status": "submission_pending"})
        )
    submit_metrics.main()
    assert len(submissions) == 1
    data = submissions[0]
    assert data["type"] == "jsonl"
    assert data["source"]["content"] == [{"item": rows[1]}]
    assert criteria[0]["data_mapping"]["response"] == "{{item.response}}"
    assert criteria[0]["data_mapping"]["output_items"] == "{{item.output_items}}"
