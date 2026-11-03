"""Read a Foundry run without submitting or repeating model work."""

import argparse
import json
import time
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential
from pydantic import BaseModel, Field, JsonValue

from cs_platform.settings import PlatformSettings
from csai.environment import load_environment

JUDGES = ("task_adherence", "intent_resolution", "coherence", "tool_call_accuracy")


class Criterion(BaseModel):
    """Fields needed to detect evaluator failures hidden by run-level counts."""

    name: str
    score: float | None = None
    status: str | None = None
    sample: dict[str, JsonValue] = Field(default_factory=dict)


class OutputItem(BaseModel):
    """The relevant subset of the service's output-item schema."""

    id: str
    results: list[Criterion]


def judge_errors(rows: list[OutputItem]) -> list[str]:
    """Require a numeric result from every requested judge on every row."""
    errors: list[str] = []
    for row in rows:
        results = {result.name: result for result in row.results}
        for name in JUDGES:
            result = results.get(name)
            if result is None:
                errors.append(f"{row.id}/{name}: missing result")
            elif result.status == "error" or result.score is None:
                errors.append(f"{row.id}/{name}: {json.dumps(result.sample)}")
    return errors


def main() -> None:
    """Retain the service response, outputs and conservative usage accounting."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True, help="Private, gitignored directory")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    load_environment()
    settings = PlatformSettings.from_env()
    args.output.mkdir(parents=True, exist_ok=True)
    with (
        AzureCliCredential() as credential,
        AIProjectClient(settings.foundry_project_endpoint, credential) as project,
        project.get_openai_client(max_retries=0) as client,
    ):
        while True:
            run = client.evals.runs.retrieve(args.run, eval_id=args.evaluation)
            data = run.model_dump(mode="json", warnings=False)
            (args.output / "run.json").write_text(json.dumps(data, indent=2))
            print(f"Status: {run.status}", flush=True)
            if run.status not in ("queued", "in_progress") or not args.wait:
                break
            time.sleep(20)
        if run.status in ("queued", "in_progress"):
            print(f"Still running: {run.id}. No resubmission.")
            raise SystemExit(3)
        rows = [
            row.model_dump(mode="json", warnings=False)
            for row in client.evals.runs.output_items.list(args.run, eval_id=args.evaluation)
        ]
    (args.output / "outputs.json").write_text(json.dumps(rows, indent=2))
    errors = judge_errors([OutputItem.model_validate(row) for row in rows])
    usage = sum(entry.total_tokens for entry in run.per_model_usage)
    summary = {
        "status": run.status,
        "rows": len(rows),
        "judge_errors": errors,
        "conservative_tokens": usage,
        "report_url": run.report_url,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if run.status != "completed" or not rows or errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
