"""Compare Foundry code scores with local scores on exactly the same outputs."""

import argparse
import json
from pathlib import Path

from pydantic import JsonValue, ValidationError

from cs_platform.evals import RunOutput, score
from rca_agent.report import RcaReport
from rca_evals import load_suite

from .graders import called_tools
from .results import OutputItem


class ScoredItem(OutputItem):
    """Keep row identity alongside the service's per-metric execution results."""

    datasource_item: dict[str, JsonValue]


def main() -> None:
    """Fail on missing/error scores or any per-case absolute difference above 1e-12."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--retained-scores",
        type=Path,
        help="Also report immutable historical scores, without rewriting them",
    )
    args = parser.parse_args()
    dataset = {
        row["case_id"]: row for row in map(json.loads, args.dataset.read_text().splitlines())
    }
    suite = load_suite()
    cases = {case.id: case for case in suite.cases}
    comparisons: list[dict[str, JsonValue]] = []
    retained = json.loads(args.retained_scores.read_text()) if args.retained_scores else None
    for raw in json.loads(args.results.read_text()):
        row = ScoredItem.model_validate(raw)
        source = row.datasource_item.get("item", row.datasource_item)
        if not isinstance(source, dict):
            raise ValueError("Missing source dataset item")
        case_id = str(source["case_id"])
        item = dataset[case_id]
        try:
            report = RcaReport.model_validate_json(item["response"])
        except ValidationError:
            report = None
        expected = score(
            suite,
            cases[case_id],
            RunOutput(
                text=item["response"],
                value=report,
                tool_calls=sorted(called_tools(item["output_items"])),
            ),
        )
        expected["calibration_score"] = 1 - expected["calibration"]
        for result in row.results:
            if result.score is None or result.status == "error":
                raise ValueError(f"{case_id}/{result.name}: {result.sample}")
            value = expected[result.name]
            difference = abs(value - result.score)
            comparisons.append(
                {
                    "case_id": case_id,
                    "metric": result.name,
                    "local": value,
                    "foundry": result.score,
                    "absolute_difference": difference,
                }
            )
            if retained is not None:
                original = (
                    1 - retained[case_id]["calibration"]
                    if result.name == "calibration_score"
                    else retained[case_id][result.name]
                )
                comparisons[-1].update(
                    {
                        "retained_local": original,
                        "retained_absolute_difference": abs(original - result.score),
                    }
                )
            if difference > 1e-12:
                raise ValueError(f"Parity mismatch: {comparisons[-1]}")
    if not comparisons:
        raise ValueError("No scores to compare")
    args.output.write_text(json.dumps(comparisons, indent=2) + "\n")
    print(f"Parity passes: {len(comparisons)} per-case scores")


if __name__ == "__main__":
    main()
