"""Export an immutable local measurement for code-only Foundry scoring."""

import argparse
import hashlib
import json
from pathlib import Path

from cs_platform.eval_runs import read_run
from cs_platform.evals import is_plumbing
from csai.eval_publish import publication_from_record

from .graders import augment


def export(reference: Path, output: Path) -> None:
    """Keep retained answers, truth, calls and scores; never invoke a target."""
    record = read_run(reference)
    if record.status != "complete":
        raise ValueError("A retained scoreboard requires a complete measurement")
    if any(
        is_plumbing(row.output, error_policy=record.result.error_policy)
        for row in record.result.cases
    ):
        raise ValueError("Resolve plumbing exclusions explicitly before export")
    publication = publication_from_record(reference)
    rows = []
    for row in publication.rows:
        rows.append(
            {
                "case_id": row.case_id,
                "repeat": row.repeat,
                "query": row.query,
                "response": row.response,
                "expected": row.ground_truth["expected"],
                "truth": row.ground_truth["truth"],
                "cohort": row.cohort,
                "output_items": row.tool_calls,
                "source": "retained local outputs",
            }
        )
    if len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("Use a single-repeat retained measurement")
    output.mkdir(parents=True, exist_ok=True)
    source = output / "retained.jsonl"
    source.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    augment(source, output / "scoring.jsonl")
    (output / "retained-scores.json").write_text(
        json.dumps({row.case_id: row.scores for row in publication.rows}, indent=2) + "\n"
    )
    hashes = {
        name: hashlib.sha256((reference / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "events.jsonl", "episodes.jsonl", "completion.json")
    }
    (output / "source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"Exported {len(rows)} retained local outputs; no target or model calls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.reference, args.output)
