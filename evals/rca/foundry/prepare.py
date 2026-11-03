"""Export existing synthetic cases for Foundry; never invoke an agent."""

import argparse
import json
from pathlib import Path

from csai.eval_publish import publication_from_record
from rca_evals import load_suite

SMOKE_CASES = {"SC-001", "SC-002", "SC-019", "SC-031", "SC-035"}


def main() -> None:
    """Write suite answer keys and retained tool schemas into local JSONL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = publication_from_record(args.reference)
    definitions = {row.case_id: row.tool_definitions for row in reference.rows}
    cases = [case for case in load_suite().cases if case.id in SMOKE_CASES]
    rows = [
        {
            "case_id": case.id,
            "query": case.input,
            "expected": case.expected,
            "truth": case.truth.model_dump(mode="json") if case.truth else None,
            "tool_definitions": definitions[case.id],
        }
        for case in cases
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "smoke.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    print(f"smoke: {len(rows)} cases")


if __name__ == "__main__":
    main()
