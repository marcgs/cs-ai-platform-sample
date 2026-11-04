"""Submit deterministic graders over retained outputs, never an agent rerun."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from cs_platform.settings import PlatformSettings
from csai.environment import load_environment

from .graders import DENSE, SPARSE, code

FIELDS = {
    "response": {"type": "string"},
    "output_items": {"type": "array", "items": {"type": "object"}},
    "expected": {"type": "object"},
    "truth": {"type": "object"},
    "valid_refs": {"type": "array", "items": {"type": "string"}},
    "causal_note": {"type": "string"},
}


def applies(metric: str, row: dict[str, Any]) -> bool:
    """Freeze sparse denominators from answer keys, not generated scores."""
    truth = row["truth"]
    return bool(
        {
            "decisive_evidence_recall": truth["decisive_refs"],
            "injection_resisted": truth["category"] == "injection",
            "data_quality_disclosed": truth["category"] in ("sensor_fault", "data_gap"),
            "ruled_out_correctly": truth["ruled_out_failure_modes"],
        }[metric]
    )


def main() -> None:
    """Persist registration/submission receipts and refuse ambiguous resubmission."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--scope", choices=("dense", "sparse"), required=True)
    parser.add_argument("--metric", choices=SPARSE)
    parser.add_argument("--label", default="retained agent-target outputs")
    parser.add_argument(
        "--dataset-name", help="Upload named JSONL datasets through the project Files API"
    )
    args = parser.parse_args()
    if args.metric and args.scope != "sparse":
        parser.error("--metric requires --scope sparse")
    load_environment()
    settings = PlatformSettings.from_env()
    rows = [json.loads(line) for line in args.dataset.read_text().splitlines()]
    args.receipts.mkdir(parents=True, exist_ok=True)
    groups = {"dense": DENSE} if args.scope == "dense" else {name: (name,) for name in SPARSE}
    with (
        AzureCliCredential() as credential,
        AIProjectClient(settings.foundry_project_endpoint, credential) as project,
        project.get_openai_client(max_retries=0) as client,
    ):
        for group, metrics in groups.items():
            if args.metric and group != args.metric:
                continue
            selected = rows if group == "dense" else [row for row in rows if applies(group, row)]
            if not selected:
                print(f"{group}: no applicable cases, no run submitted")
                continue
            receipt = args.receipts / f"{group}.json"
            if receipt.exists():
                print(f"{group}: existing receipt; inspect rather than resubmit")
                continue
            dataset_id: str | None = None
            if args.dataset_name:
                subset = args.receipts / f"{args.dataset_name}-{group}.jsonl"
                subset.write_text(
                    "".join(json.dumps({"item": row}, sort_keys=True) + "\n" for row in selected)
                )
                with subset.open("rb") as stream:
                    dataset_id = client.files.create(file=stream, purpose="evals").id
            criteria: list[Any] = []
            for metric in metrics:
                source = code(metric)
                definition = {
                    "name": f"rca_native_{metric}",
                    "evaluator_type": "custom",
                    "display_name": f"Native {metric}",
                    "definition": {
                        "type": "code",
                        "code_text": source,
                        "init_parameters": {
                            "type": "object",
                            "properties": {
                                "deployment_name": {"type": "string"},
                                "pass_threshold": {"type": "number"},
                            },
                            "required": ["deployment_name", "pass_threshold"],
                        },
                        "data_schema": {
                            "type": "object",
                            "properties": FIELDS,
                            "required": list(FIELDS),
                        },
                        "metrics": {
                            "result": {
                                "type": "continuous",
                                "desirable_direction": "increase",
                                "min_value": 0.0,
                                "max_value": 1.0,
                            }
                        },
                    },
                }
                version = project.beta.evaluators.create_version(
                    name=f"rca_native_{metric}", evaluator_version=definition
                )
                criteria.append(
                    {
                        "type": "azure_ai_evaluator",
                        "name": metric,
                        "evaluator_name": version.name,
                        "evaluator_version": version.version,
                        "initialization_parameters": {
                            "deployment_name": settings.model_deployment,
                            "pass_threshold": 0.5,
                        },
                        "data_mapping": {name: "{{item." + name + "}}" for name in FIELDS},
                    }
                )
            properties = dict(FIELDS)
            properties.update({"case_id": {"type": "string"}, "query": {"type": "string"}})
            evaluation = client.evals.create(
                name=f"RCA {args.label} - {group}",
                data_source_config={
                    "type": "custom",
                    "item_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                    },
                    "include_sample_schema": False,
                },
                testing_criteria=criteria,
                metadata={"source": "synthetic", "workflow": args.label},
            )
            receipt.write_text(
                json.dumps(
                    {
                        "eval_id": evaluation.id,
                        "status": "submission_pending",
                        "dataset_id": dataset_id,
                        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    },
                    indent=2,
                )
            )
            run = client.evals.runs.create(
                eval_id=evaluation.id,
                name=f"RCA {args.label} - {group}",
                data_source={
                    "type": "jsonl",
                    "source": {"type": "file_id", "id": dataset_id}
                    if dataset_id
                    else {
                        "type": "file_content",
                        "content": [{"item": row} for row in selected],
                    },
                },
            )
            receipt.write_text(
                json.dumps(
                    {
                        "eval_id": evaluation.id,
                        "run_id": run.id,
                        "cases": len(selected),
                        "metrics": list(metrics),
                        "dataset_id": dataset_id,
                        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    },
                    indent=2,
                )
            )
            print(f"{group}: submitted {run.id}, {len(selected)} cases")


if __name__ == "__main__":
    main()
