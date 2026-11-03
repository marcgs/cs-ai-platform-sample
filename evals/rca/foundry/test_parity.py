"""Verify service-score parity across the CLI and SDK source-item shapes."""

import json
from typing import TYPE_CHECKING

import pytest

from .parity import main

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
    monkeypatch.setattr(
        "sys.argv",
        ["parity", "--results", str(results), "--dataset", str(dataset), "--output", str(output)],
    )
    if remote_score:
        with pytest.raises(ValueError, match="Parity mismatch"):
            main()
        assert not output.exists()
    else:
        main()
        assert json.loads(output.read_text())[0]["absolute_difference"] == 0
