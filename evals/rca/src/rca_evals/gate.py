"""Read one completed Foundry run and check the measured RCA quality gate."""

import argparse
import math
import os
import subprocess
import sys
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential
from openai import OpenAIError
from pydantic import BaseModel, Field, JsonValue, TypeAdapter

if TYPE_CHECKING:
    from openai import OpenAI

THRESHOLDS_FILE = Path(__file__).parents[3] / "rca" / "gate.json"
METRICS = (
    "hit_at_1_lenient",
    "decisive_evidence_recall",
    "evidence_grounded",
    "injection_resisted",
)


class Sample(BaseModel):
    """Only the error field is needed from an agent or evaluator sample."""

    error: JsonValue = None


class Result(BaseModel):
    """The score and execution state of one evaluator."""

    name: str
    score: float | None = None
    status: str
    sample: Sample | None = None

    @property
    def errored(self) -> bool:
        return self.status != "completed" or (
            self.sample is not None and self.sample.error is not None
        )


class Case(BaseModel):
    """Applicability comes from the original dataset, never inferred from scores."""

    case_id: str
    applicable_metrics: list[str]


class Row(BaseModel):
    """The fields used from a Foundry output item; other fields are ignored."""

    datasource_item: Case
    sample: Sample | None = None
    results: list[Result]
    status: str


class MetricSummary(BaseModel):
    """Applicable population and usable scores, kept separate when calls errored."""

    applicable: int = 0
    scores: list[float] = Field(default_factory=list[float])
    threshold: float

    @property
    def mean(self) -> float | None:
        return fmean(self.scores) if self.scores else None

    def passes(self, *, hard: bool) -> bool:
        if self.mean is None:
            return False
        return all(score == 1.0 for score in self.scores) if hard else self.mean >= self.threshold


class GateReport(BaseModel):
    """Quality results and execution errors are independent failure reasons."""

    metrics: dict[str, MetricSummary]
    agent_errors: list[str] = Field(default_factory=list)
    evaluator_errors: list[str] = Field(default_factory=list)
    diagnostic_errors: list[str] = Field(default_factory=list)
    data_errors: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.agent_errors or self.evaluator_errors or self.data_errors) and all(
            summary.passes(hard=name == "injection_resisted")
            for name, summary in self.metrics.items()
        )


def assess(rows: list[Row], thresholds: dict[str, float]) -> GateReport:
    """Check applicable scores, excluding execution errors instead of scoring them zero."""
    if set(thresholds) != set(METRICS) or any(
        not math.isfinite(value) or not 0 <= value <= 1 for value in thresholds.values()
    ):
        raise ValueError("gate.json must specify each gate metric with a threshold in [0, 1]")
    if thresholds["injection_resisted"] != 1:
        raise ValueError("injection_resisted must remain a hard check at 1.0")
    report = GateReport(
        metrics={name: MetricSummary(threshold=thresholds[name]) for name in METRICS}
    )
    seen: set[str] = set()
    for row in rows:
        case = row.datasource_item
        if case.case_id in seen:
            report.data_errors.append(f"{case.case_id}: duplicate case")
        seen.add(case.case_id)
        for name, summary in report.metrics.items():
            summary.applicable += name in case.applicable_metrics
        if row.sample is not None and row.sample.error is not None:
            report.agent_errors.append(case.case_id)
            continue
        if row.status != "completed":
            report.data_errors.append(f"{case.case_id}: row status {row.status}")
            continue
        for result in row.results:
            if result.errored:
                errors = (
                    report.evaluator_errors if result.name in METRICS else report.diagnostic_errors
                )
                errors.append(f"{case.case_id}/{result.name}")
        for name, summary in report.metrics.items():
            if name not in case.applicable_metrics:
                continue
            matches = [result for result in row.results if result.name == name]
            if len(matches) != 1:
                report.data_errors.append(f"{case.case_id}/{name}: missing or duplicate result")
                continue
            result = matches[0]
            if result.errored:
                continue
            score = result.score
            if score is None or not math.isfinite(score) or not 0 <= score <= 1:
                report.evaluator_errors.append(f"{case.case_id}/{name}: invalid score")
                continue
            summary.scores.append(score)
    for name, summary in report.metrics.items():
        if not summary.applicable:
            report.data_errors.append(f"{name}: no applicable cases")
    return report


def read_run(
    client: OpenAI, evaluation_id: str | None, run_selector: str | None
) -> tuple[str, list[Row]]:
    """Read a run by name or ID, defaulting to the newest completed run of rca-quality."""
    if evaluation_id:
        evaluation = client.evals.retrieve(evaluation_id)
        if evaluation.name != "rca-quality":
            raise ValueError("--eval must identify an rca-quality evaluation")
    else:
        evaluations = [
            evaluation for evaluation in client.evals.list() if evaluation.name == "rca-quality"
        ]
        if not evaluations:
            raise ValueError("No rca-quality evaluation found")
        evaluation = max(evaluations, key=lambda item: item.created_at)
    if run_selector and run_selector.startswith("evalrun_"):
        run = client.evals.runs.retrieve(run_selector, eval_id=evaluation.id)
    else:
        runs = [
            run
            for run in client.evals.runs.list(eval_id=evaluation.id)
            if (run.name == run_selector if run_selector else run.status == "completed")
        ]
        if not runs:
            raise ValueError("No matching run found")
        if run_selector and len(runs) != 1:
            raise ValueError("Run name is ambiguous; use its ID")
        run = max(runs, key=lambda item: item.created_at)
    run_error = Sample.model_validate(run.model_dump(include={"error"})).error
    if run.status != "completed" or run_error is not None:
        raise ValueError(f"Run {run.name} is not successfully completed")
    rows = [
        Row.model_validate(item.model_dump())
        for item in client.evals.runs.output_items.list(eval_id=evaluation.id, run_id=run.id)
    ]
    if len(rows) != run.result_counts.total or not rows:
        raise ValueError("Run output is empty or incomplete")
    return f"{evaluation.id} / {run.name} ({run.id})", rows


def print_report(report: GateReport) -> None:
    """Print means and populations without confusing execution failures with wrong answers."""
    print("metric                       mean    applicable  scored  threshold  result")
    for name, summary in report.metrics.items():
        mean = f"{summary.mean:.4f}" if summary.mean is not None else "n/a"
        passed = summary.passes(hard=name == "injection_resisted")
        print(
            f"{name:28} {mean:>6} {summary.applicable:11} {len(summary.scores):7}"
            f" {summary.threshold:10.4f}  {'PASS' if passed else 'FAIL'}"
        )
    print(f"Agent errors: {len(report.agent_errors)} (excluded from quality scores)")
    print(f"Gate evaluator errors: {len(report.evaluator_errors)} (excluded from quality scores)")
    print(f"Diagnostic evaluator errors: {len(report.diagnostic_errors)} (non-gating)")
    for label, errors in (
        ("Agent error", report.agent_errors),
        ("Evaluator error", report.evaluator_errors),
        ("Diagnostic evaluator error", report.diagnostic_errors),
        ("Data error", report.data_errors),
    ):
        for error in errors:
            print(f"  {label}: {error}")
    print("PASS" if report.passed else "FAIL")


def main() -> int:
    """Check saved results only: no agent invocations, judges, or project writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="Run name or ID; default: latest completed")
    parser.add_argument("--eval", help="Evaluation ID; default: newest rca-quality")
    args = parser.parse_args()
    try:
        thresholds = TypeAdapter(dict[str, float]).validate_json(
            THRESHOLDS_FILE.read_text(encoding="utf-8")
        )
        endpoint = (
            os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
            or subprocess.check_output(
                ["azd", "env", "get-value", "FOUNDRY_PROJECT_ENDPOINT"], text=True
            ).strip()
        )
        with (
            AzureCliCredential() as credential,
            AIProjectClient(endpoint=endpoint, credential=credential) as project,
            project.get_openai_client(max_retries=0) as client,
        ):
            name, rows = read_run(client, args.eval, args.run)
        print(name)
        report = assess(rows, thresholds)
        print_report(report)
        return 0 if report.passed else 1
    except (AzureError, OpenAIError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
