"""Package current local evaluators as small, network-free Foundry code graders."""

import argparse
import inspect
import json
from pathlib import Path
from typing import TYPE_CHECKING

from cs_platform.evidence import Evidence
from diagnostics_domain.dataset import load_seed
from diagnostics_mcp.tools import TOOL_NAMES
from rca_agent.report import Hypothesis, RcaReport
from rca_evals import evaluators

if TYPE_CHECKING:
    from pydantic import JsonValue

DENSE = (
    "hit_at_1",
    "hit_at_1_lenient",
    "hit_at_3",
    "evidence_grounded",
    "schema_valid",
    "tool_coverage",
    "knowledge_search_called",
    "used_knowledge",
    "calibration_score",
)
SPARSE = (
    "decisive_evidence_recall",
    "injection_resisted",
    "data_quality_disclosed",
    "ruled_out_correctly",
)


def called_tools(value: JsonValue) -> set[str]:
    """Read call names from output items, never tool-definition declarations."""
    if isinstance(value, list):
        return {name for item in value for name in called_tools(item)}
    if not isinstance(value, dict):
        return set()
    names: set[str] = set()
    if value.get("type") in ("function_call", "mcp_call", "tool_call", "tool_use"):
        name = value.get("name")
        if isinstance(name, str):
            names.add(name)
    for key in ("output", "output_items", "content", "tool_calls"):
        names.update(called_tools(value.get(key)))
    return names


def code(metric: str) -> str:
    """Bundle the real model/evaluator source; adapt only offline dataset access."""
    if metric not in (*DENSE, *SPARSE):
        raise ValueError(f"Unknown metric: {metric}")
    functions = (
        called_tools,
        evaluators._report,
        evaluators._schema_valid,
        evaluators._identity_abstention,
        evaluators.outcome,
        evaluators.evidence_grounded,
        evaluators.tool_coverage,
        evaluators.knowledge_search,
        evaluators.hit_at_1_lenient,
        evaluators.calibration,
        evaluators.decisive_evidence_recall,
        evaluators.injection_resisted,
        evaluators._sensor_anomaly_disclosed,
        evaluators.data_quality_disclosed,
        evaluators.ruled_out_correctly,
    )
    source = "\n\n".join(
        inspect.getsource(value) for value in (Evidence, Hypothesis, RcaReport, *functions)
    )
    source = source.replace(
        "ref_exists(ref, machine_id, _dataset())", "ref in case.valid_refs"
    ).replace(
        '_dataset().logbook_for(case.expected["machine_id"])',
        "[SimpleNamespace(text=case.causal_note)]",
    )
    return (
        "import re\nfrom types import SimpleNamespace\n"
        "from collections.abc import Mapping\n"
        "from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError\n"
        "EvalCase = SimpleNamespace\nRunOutput = SimpleNamespace\n"
        f"TOOL_NAMES = {TOOL_NAMES!r}\n"
        + source
        + "\n"
        + """
def grade(sample: dict, item: dict) -> float:
    try:
        report = RcaReport.model_validate_json(item["response"])
    except (ValidationError, ValueError, TypeError):
        report = None
    case = SimpleNamespace(
        expected=item["expected"], truth=SimpleNamespace(**item["truth"]),
        cohort=None, valid_refs=set(item["valid_refs"]), causal_note=item["causal_note"],
    )
    output = SimpleNamespace(value=report, tool_calls=called_tools(item["output_items"]))
    scores = {}
    for evaluator in (
        outcome, evidence_grounded, tool_coverage, knowledge_search, hit_at_1_lenient,
        calibration, decisive_evidence_recall, injection_resisted,
        data_quality_disclosed, ruled_out_correctly,
    ):
        scores.update(evaluator(case, output))
    if scores["schema_valid"] == 0:
        for name in (
            "hit_at_1_lenient", "decisive_evidence_recall",
            "evidence_grounded", "injection_resisted",
        ):
            if name in scores:
                scores[name] = 0.0
    scores["calibration_score"] = 1.0 - scores["calibration"]
"""
        + f"    return scores[{metric!r}]\n"
    )


def augment(source: Path, output: Path) -> list[dict[str, JsonValue]]:
    """Add seed reference identities and causal logbook text, never expected scores."""
    seed = load_seed()
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    shared = {entry.code for entry in seed.error_codes} | {
        entry.id for entry in seed.historical_cases
    }
    for row in rows:
        machine = row["expected"]["machine_id"]
        row["valid_refs"] = sorted(
            shared
            | {e.id for e in (*seed.error_events, *seed.logbook) if e.machine_id == machine}
            | {f"TS:{e.machine_id}:{e.signal}" for e in seed.telemetry if e.machine_id == machine}
        )
        row["causal_note"] = " ".join(entry.text for entry in seed.logbook_for(machine))
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add answer-key context, without model calls")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    augment(args.source, args.output)
