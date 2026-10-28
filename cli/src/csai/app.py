"""``csai``: the CS AI platform's command line."""

import asyncio
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path  # noqa: TC003 - typer reads annotations at runtime
from typing import TYPE_CHECKING, Annotated

import typer
from azure.identity.aio import DefaultAzureCredential

from cs_platform.evals import EvalSuite, run_suite
from cs_platform.settings import PlatformSettings, SettingsError
from csai import foundry
from csai.environment import load_environment
from csai.targets import AGENTS, hosted_target, local_target

if TYPE_CHECKING:
    from cs_platform.evals import CaseResult, SuiteResult
    from csai.targets import AgentEntry

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def configure(
    azd: Annotated[
        bool, typer.Option(help="Read settings from the active azd environment.")
    ] = True,
) -> None:
    """Command line for the CS AI platform."""
    load_environment(use_azd=azd)


class TargetKind(StrEnum):
    LOCAL = "local"
    HOSTED = "hosted"


def describe(result: CaseResult) -> str:
    scores = " ".join(f"{name}={value:.2f}" for name, value in sorted(result.scores.items()))
    error = f"  ERROR {result.output.error}" if result.output.error else ""
    return f"{result.case_id:<10} {result.output.duration_s:6.1f}s  {scores}{error}"


def report(suite: EvalSuite, result: SuiteResult) -> list[str]:
    typer.echo(f"\n{suite.name}: {len(result.cases)} cases")
    metrics = result.metrics
    for name, value in metrics.items():
        minimum = suite.thresholds.minimums.get(name)
        gate = f"  (min {minimum:.2f})" if minimum is not None else ""
        mark = "FAIL" if minimum is not None and value < minimum else "ok  "
        typer.echo(f"  {mark} {name:<20} {value:.2f}{gate}")
    return result.failures(suite.thresholds)


async def evaluate(
    entry: AgentEntry, suite: EvalSuite, target: TargetKind, concurrency: int
) -> SuiteResult:
    async with DefaultAzureCredential() as credential:
        if target is TargetKind.LOCAL:
            run = local_target(entry, PlatformSettings.from_env(), credential)
        else:
            endpoint = os.environ.get(entry.responses_endpoint_variable)
            if not endpoint:
                raise SettingsError(f"{entry.responses_endpoint_variable} is not set; deploy first")
            run = hosted_target(entry, endpoint, credential)
        return await run_suite(
            suite, run, concurrency=concurrency, on_result=lambda r: typer.echo(describe(r))
        )


@app.command("eval")
def eval_command(
    agent: Annotated[str, typer.Argument(help=f"One of: {', '.join(AGENTS)}.")] = "rca",
    target: Annotated[TargetKind, typer.Option(help="Where the agent runs.")] = TargetKind.LOCAL,
    case: Annotated[list[str] | None, typer.Option(help="Run only these case IDs.")] = None,
    concurrency: Annotated[int, typer.Option(min=1, help="Cases run in parallel.")] = 3,
    output: Annotated[Path | None, typer.Option(help="Write per-case results (JSONL).")] = None,
    publish: Annotated[
        bool, typer.Option(help="Also score the run with Foundry's built-in evaluators.")
    ] = False,
) -> None:
    """Run the agent's eval suite and fail (exit 1) when a metric is below its threshold."""
    entry = AGENTS.get(agent)
    if entry is None:
        raise typer.BadParameter(f"unknown agent {agent!r}", param_hint="AGENT")
    suite = entry.load_suite()
    if case:
        selected = tuple(c for c in suite.cases if c.id in case)
        suite = EvalSuite(suite.name, selected, suite.thresholds, suite.evaluators)
    try:
        result = asyncio.run(evaluate(entry, suite, target, concurrency))
    except SettingsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    if output is not None:
        output.write_text(result.to_jsonl(), encoding="utf-8")
    failures = report(suite, result)
    if publish:
        settings = PlatformSettings.from_env()
        label = f"{target}-{datetime.now(UTC):%Y%m%d-%H%M%S}"
        typer.echo(f"\nPublishing {label} to Foundry (built-in evaluators)...")
        try:
            url = foundry.publish(
                suite,
                result,
                endpoint=settings.foundry_project_endpoint,
                model=settings.model_deployment,
                label=label,
            )
        except foundry.FoundryEvalError as error:
            # Publishing is reporting, not gating: the code-based gate below still decides.
            typer.echo(f"warning: {error}", err=True)
        else:
            typer.echo(f"Foundry report: {url}")
    if failures:
        typer.echo("\nGate failed: " + "; ".join(failures), err=True)
        raise typer.Exit(1)
    typer.echo("\nGate passed.")


def main() -> None:
    app()
