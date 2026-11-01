"""Offline eval reporting and the extensible eval command group."""

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 - Typer resolves the command annotation at runtime
from typing import TYPE_CHECKING, Annotated

import typer
from typer.core import TyperGroup

from cs_platform.eval_runs import rebuild_report
from csai.environment import load_environment

if TYPE_CHECKING:
    from typer._click.core import Context

    from cs_platform.episodes import Episode
    from cs_platform.eval_runs import RunWriter


@dataclass(frozen=True)
class EvalEnvironment:
    use_azd: bool


class DurableEpisodes(list["Episode"]):
    """Keep the target's callback compatible while recording each real episode first."""

    def __init__(self, writer: RunWriter) -> None:
        super().__init__()
        self.writer = writer

    def append(self, episode: Episode) -> None:
        self.writer.episode(episode)


class EvalGroup(TyperGroup):
    """Keep the original default-agent invocation alongside the report subcommand."""

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        if not args or (args[0] not in self.commands and args[0] not in {"--help", "-h"}):
            args = ["rca", *args]
        return super().parse_args(ctx, args)


eval_app = typer.Typer(
    cls=EvalGroup, no_args_is_help=False, help="Run an eval suite or report an existing run."
)


@eval_app.callback()
def configure_eval(ctx: typer.Context) -> None:
    """Reporting is entirely offline; only running loads deployment settings."""
    if ctx.invoked_subcommand != "report":
        options = ctx.find_root().obj
        load_environment(use_azd=options.use_azd if isinstance(options, EvalEnvironment) else True)


@eval_app.command("report")
def report_command(
    results_dir: Annotated[
        Path, typer.Argument(help="Results directory, .run directory or JSONL.")
    ],
) -> None:
    """Rebuild the summary and private HTML from durable records, without model calls."""
    try:
        record = rebuild_report(results_dir)
    except (OSError, ValueError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(f"{record.manifest.suite}: {record.status}; {len(record.result.cases)} case-runs")
    if record.failures:
        typer.echo("Gate failed: " + "; ".join(record.failures), err=True)
        raise typer.Exit(1)
    typer.echo(
        "Gate passed."
        if any(case.gated for case in record.result.cases)
        else "Informational run complete; no regression gate evaluated."
    )
