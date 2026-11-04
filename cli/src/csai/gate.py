"""``csai gate``: the quality gate, computed from Foundry evaluation runs.

Foundry reports a pass count per evaluator against a per-row threshold. The gate
(ADR 0009, ADR 0010) needs minimum means over the cases each metric applies to, and a
hard check where any failed case fails the gate.
This reads the rows of one or more runs and applies ``thresholds.yaml`` the way the local
gate does: feedback cases stay report-only, a row without a result for a metric doesn't
apply to it, and an evaluator error fails the gate rather than being skipped.
"""

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import TYPE_CHECKING, Annotated, Any

import typer
import yaml
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel, ConfigDict, Field

from cs_platform.settings import PlatformSettings, SettingsError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

THRESHOLDS = Path("evals/rca/src/rca_evals/thresholds.yaml")
REPORT_ONLY_COHORTS = frozenset({"feedback"})
SKIPPED = frozenset({"skipped", "not_applicable"})


class Thresholds(BaseModel):
    """The gate's configuration, as in ``thresholds.yaml``."""

    model_config = ConfigDict(extra="forbid")

    minimums: dict[str, float] = Field(description="Minimum mean score per metric.")
    hard_checks: frozenset[str] = frozenset()
    provisional: bool = False

    @classmethod
    def load(cls, path: Path) -> Thresholds:
        return cls.model_validate(yaml.safe_load(path.read_text("utf-8")))


@dataclass(frozen=True)
class Score:
    """One evaluator's result on one row. ``value`` is None when it didn't score."""

    value: float | None
    status: str


@dataclass(frozen=True)
class Row:
    """One case-run as Foundry scored it."""

    case_id: str
    repeat: int
    cohort: str
    scores: Mapping[str, Score]

    @property
    def label(self) -> str:
        return f"{self.case_id}/repeat-{self.repeat}"


@dataclass(frozen=True)
class MetricResult:
    name: str
    mean: float | None
    count: int
    minimum: float

    @property
    def passed(self) -> bool:
        return self.mean is not None and self.mean >= self.minimum


@dataclass
class GateResult:
    metrics: list[MetricResult] = field(default_factory=list[MetricResult])
    hard_check_failures: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    hard_check_counts: dict[str, int] = field(default_factory=dict[str, int])
    errors: list[str] = field(default_factory=list[str])
    report_only: int = 0

    def failures(self) -> list[str]:
        """Why the gate fails; empty when it passes."""
        failures = list(self.errors)
        for metric in self.metrics:
            if metric.mean is None:
                failures.append(f"{metric.name}: not evaluated (no applicable rows)")
            elif not metric.passed:
                failures.append(f"{metric.name}: {metric.mean:.2f} < {metric.minimum:.2f}")
        for name, count in self.hard_check_counts.items():
            if count == 0:
                failures.append(f"{name}: hard check not evaluated (no applicable rows)")
        failures.extend(
            f"{name}: hard check failed: {', '.join(failed)}"
            for name, failed in self.hard_check_failures.items()
        )
        return failures


def evaluate_gate(rows: Iterable[Row], thresholds: Thresholds) -> GateResult:
    """Apply the gate to scored rows: minimum means, then hard checks."""
    result = GateResult()
    gated: list[Row] = []
    for row in rows:
        if row.cohort in REPORT_ONLY_COHORTS:
            result.report_only += 1
        else:
            gated.append(row)
    names = sorted(thresholds.minimums.keys() | thresholds.hard_checks)
    values: dict[str, list[tuple[Row, float]]] = {name: [] for name in names}
    for row in gated:
        for name in names:
            score = row.scores.get(name)
            if score is None or score.status in SKIPPED:
                continue
            if score.value is None or score.status not in ("completed", "passed", "failed"):
                result.errors.append(f"{name}: evaluator error on {row.label} ({score.status})")
                continue
            values[name].append((row, score.value))
    for name, minimum in thresholds.minimums.items():
        scored = [value for _, value in values[name]]
        result.metrics.append(
            MetricResult(name, mean(scored) if scored else None, len(scored), minimum)
        )
    for name in sorted(thresholds.hard_checks):
        result.hard_check_counts[name] = len(values[name])
        if failed := [row.label for row, value in values[name] if value != 1.0]:
            result.hard_check_failures[name] = failed
    return result


class _Result(BaseModel):
    name: str
    score: float | None = None
    status: str = "unknown"


class _Case(BaseModel):
    case_id: str
    repeat: int = 1
    cohort: str = "original"


class _Source(BaseModel):
    item: _Case


class _OutputItem(BaseModel):
    """The parts of a Foundry run output item the gate reads."""

    datasource_item: _Source
    results: list[_Result] = []


def rows_from_output_items(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """Turn Foundry run output items into rows; criteria are named after the metric."""
    rows: list[Row] = []
    for raw in items:
        item = _OutputItem.model_validate(raw)
        case = item.datasource_item.item
        scores = {result.name: Score(result.score, result.status) for result in item.results}
        rows.append(Row(case.case_id, case.repeat, case.cohort, scores))
    return rows


def merge_runs(runs: Mapping[str, list[Row]]) -> tuple[list[Row], list[str]]:
    """Combine rows from several runs; a metric may come from only one run."""
    owner: dict[str, str] = {}
    errors: list[str] = []
    merged: list[Row] = []
    for run, rows in runs.items():
        for name in {name for row in rows for name in row.scores}:
            if name in owner and owner[name] != run:
                errors.append(f"{name}: scored in both {owner[name]} and {run}")
            owner.setdefault(name, run)
        merged.extend(rows)
    return merged, errors


def describe(result: GateResult, thresholds: Thresholds) -> list[str]:
    lines = [
        f"{'metric':28} {'mean':>6} {'min':>6} {'rows':>5}",
        *(
            f"{m.name:28} {'-' if m.mean is None else f'{m.mean:.3f}':>6} "
            f"{m.minimum:>6.2f} {m.count:>5}  {'pass' if m.passed else 'FAIL'}"
            for m in result.metrics
        ),
    ]
    for name, count in result.hard_check_counts.items():
        failed = len(result.hard_check_failures.get(name, []))
        lines.append(f"{name:28} hard check: {count - failed}/{count} passed")
    if result.report_only:
        lines.append(f"{result.report_only} report-only (feedback) row(s) not gated")
    if thresholds.provisional:
        lines.append("Thresholds are provisional.")
    return lines


def _load_runs(evaluations: list[str], run: str | None) -> tuple[dict[str, list[Row]], list[str]]:
    """Read the chosen run of each evaluation (by name or ID) from the Foundry project."""
    endpoint = PlatformSettings.from_env().foundry_project_endpoint
    loaded: dict[str, list[Row]] = {}
    links: list[str] = []
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint, credential) as project,
        project.get_openai_client() as client,
    ):
        known = list(client.evals.list())
        for wanted in evaluations:
            matches = [e for e in known if wanted in (e.id, e.name)]
            if len(matches) != 1:
                raise typer.BadParameter(f"{len(matches)} evaluations match {wanted!r}")
            evaluation = matches[0]
            runs = [
                r
                for r in client.evals.runs.list(eval_id=evaluation.id)
                if (run is None and r.status == "completed") or run in (r.id, r.name)
            ]
            if not runs:
                raise typer.BadParameter(f"no matching completed run in {evaluation.name!r}")
            chosen = max(runs, key=lambda r: r.created_at)
            if chosen.status != "completed":
                raise typer.BadParameter(f"run {chosen.name!r} is {chosen.status}, not completed")
            items = [
                item.model_dump(mode="json", warnings=False)
                for item in client.evals.runs.output_items.list(chosen.id, eval_id=evaluation.id)
            ]
            loaded[f"{evaluation.name} / {chosen.name}"] = rows_from_output_items(items)
            if chosen.report_url:
                links.append(chosen.report_url)
    return loaded, links


def gate_command(
    evaluations: Annotated[
        list[str],
        typer.Argument(help="Foundry evaluations to gate on, by name or ID."),
    ],
    run: Annotated[
        str | None,
        typer.Option(help="Run name or ID; default: each evaluation's latest completed run."),
    ] = None,
    thresholds: Annotated[Path, typer.Option(help="Gate thresholds.")] = THRESHOLDS,
) -> None:
    """Gate on Foundry evaluation results: minimum means and hard checks."""
    config = Thresholds.load(thresholds)
    try:
        runs, links = _load_runs(evaluations, run)
    except SettingsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    rows, errors = merge_runs(runs)
    result = evaluate_gate(rows, config)
    result.errors[:0] = errors
    for name in runs:
        typer.echo(f"Run: {name}")
    for line in describe(result, config):
        typer.echo(line)
    for link in links:
        typer.echo(f"Report: {link}")
    if failures := result.failures():
        typer.echo("Gate FAILED:")
        for failure in failures:
            typer.echo(f"  {failure}")
        raise typer.Exit(1)
    typer.echo("Gate passed.")
