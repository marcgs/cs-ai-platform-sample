"""Verify service-score parity across the CLI and SDK source-item shapes."""

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from cs_platform.eval_reporting import RunMetadata
from cs_platform.eval_runs import RunWriter
from cs_platform.evals import CaseResult, RunOutput, score
from rca_evals import load_suite

from .parity import main
from .retained import export

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("remote_score", [0.0, 1.0])
def test_actual_service_scores_not_only_bundled_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool, remote_score: float
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps({"case_id": "SC-001", "response": "{}", "output_items": []}) + "\n"
    )
    results = tmp_path / "outputs.json"
    item = {"case_id": "SC-001"}
    results.write_text(
        json.dumps(
            [
                {
                    "id": "row",
                    "datasource_item": {"item": item} if nested else item,
                    "results": [
                        {
                            "name": "schema_valid",
                            "score": remote_score,
                            "status": "completed",
                            "sample": None,
                        }
                    ],
                }
            ]
        )
    )
    output = tmp_path / "parity.json"
    historical = tmp_path / "retained-scores.json"
    historical.write_text(json.dumps({"SC-001": {"schema_valid": 1.0}}))
    monkeypatch.setattr(
        "sys.argv",
        [
            "parity",
            "--results",
            str(results),
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--retained-scores",
            str(historical),
        ],
    )
    if remote_score:
        with pytest.raises(ValueError, match="Parity mismatch"):
            main()
        assert not output.exists()
    else:
        main()
        comparison = json.loads(output.read_text())[0]
        assert comparison["absolute_difference"] == 0
        assert comparison["retained_local"] == 1
        assert comparison["retained_absolute_difference"] == 1
        assert json.loads(historical.read_text()) == {"SC-001": {"schema_valid": 1.0}}


def test_retained_export_preserves_original_journal_and_separates_scores(
    tmp_path: Path,
) -> None:
    suite = load_suite()
    case = suite.cases[0]
    suite = replace(suite, cases=(case,))
    writer = RunWriter(
        suite,
        tmp_path / "reference.jsonl",
        RunMetadata(
            agent_revision="fixture",
            harness_revision="fixture",
            model="scripted",
            target="local",
        ),
        concurrency=1,
    )
    output = RunOutput(text="{}", tool_trace_complete=True, tool_trace=[])
    scores = score(suite, case, output)
    scores["evidence_grounded"] = 1.0
    writer.start(case, 1)
    writer.start_attempt(case, 1, 1)
    writer.attempt(case, 1, output)
    writer.completed(
        CaseResult(
            case_id=case.id,
            input=case.input,
            split=case.split,
            scores=scores,
            output=output,
        )
    )
    writer.finish()
    reference = tmp_path / "reference.run"
    original = {file.name: file.read_bytes() for file in reference.iterdir() if file.is_file()}

    destination = tmp_path / "export"
    export(reference, destination)

    assert original == {
        file.name: file.read_bytes() for file in reference.iterdir() if file.is_file()
    }
    row = json.loads((destination / "scoring.jsonl").read_text())
    assert row["source"] == "retained local outputs"
    assert row["case_id"] == case.id
    assert row["response"] == "{}"
    assert row["expected"] == case.expected
    assert case.truth is not None
    assert row["truth"]["category"] == case.truth.category
    assert "scores" not in row
    assert json.loads((destination / "retained-scores.json").read_text())[case.id] == scores
