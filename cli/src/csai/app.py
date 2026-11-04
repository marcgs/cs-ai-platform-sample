"""``csai``: the platform's own commands, for what azd doesn't cover.

azd provisions, deploys, runs and invokes the agent (``azd ai agent run``, ``invoke``,
``monitor``). Episodes and expert feedback live in the platform's own store, reached
through the platform API, so ``csai`` reads episodes and records feedback.
"""

from typing import TYPE_CHECKING, Annotated

import typer

from cs_platform.episodes import Verdict  # noqa: TC001 - typer reads annotations at runtime
from cs_platform.settings import SettingsError
from csai.environment import load_environment
from csai.platform import PlatformApiError, PlatformClient
from platform_api.api import FeedbackRequest
from rca_agent.local import render
from rca_agent.report import RcaReport

if TYPE_CHECKING:
    from cs_platform.episodes import Episode

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def configure(
    azd: Annotated[
        bool, typer.Option(help="Read settings from the active azd environment.")
    ] = True,
) -> None:
    """The platform's commands for episodes and expert feedback."""
    load_environment(use_azd=azd)


def render_output(episode: Episode) -> str | None:
    """The agent's structured output, formatted for the terminal, when we know its type."""
    if episode.output is None or episode.agent != "rca-agent":
        return None
    return render(RcaReport.model_validate(episode.output))


# --- episodes and feedback -----------------------------------------------------------------

episodes_app = typer.Typer(no_args_is_help=True, help="Inspect recorded agent runs.")
app.add_typer(episodes_app, name="episodes")


def platform() -> PlatformClient:
    try:
        return PlatformClient.from_env()
    except (SettingsError, PlatformApiError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error


@episodes_app.command("list")
def list_episodes(
    agent: Annotated[str | None, typer.Option(help="Only this agent, e.g. rca-agent.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
) -> None:
    """Recent episodes, newest first."""
    for e in platform().list_episodes(agent=agent, limit=limit):
        verdict = e.verdict.value if e.verdict else "-"
        typer.echo(
            f"{e.id}  {e.created_at:%Y-%m-%d %H:%M}  {e.agent:<10} {e.status:<9} "
            f"tools={e.tool_calls:<2} verdict={verdict:<17} {e.input[:60]}"
        )


def describe_episode(episode: Episode) -> list[str]:
    lines = [
        f"Episode {episode.id}: {episode.agent} {episode.agent_version}, {episode.status}",
        f"Created {episode.created_at:%Y-%m-%d %H:%M:%S} UTC, trace {episode.trace_id or 'n/a'}",
        *([f"Response: {episode.hosted_response_id}"] if episode.hosted_response_id else []),
        f"Input: {episode.input}",
        "",
        "Tool calls:",
    ]
    lines.extend(
        f"  {c.name}({', '.join(f'{k}={v}' for k, v in c.arguments.items())})"
        f" {c.duration_ms:.0f} ms{'  ERROR ' + c.error if c.error else ''}"
        for c in episode.tool_calls
    )
    if episode.usage:
        lines.append(f"Tokens: {episode.usage.input_tokens} in / {episode.usage.output_tokens} out")
    if episode.error:
        lines.append(f"Error: {episode.error}")
    return lines


@episodes_app.command("show")
def show_episode(episode_id: str) -> None:
    """One episode: input, tool calls, report and feedback."""
    episode = platform().get_episode(episode_id)
    typer.echo("\n".join(describe_episode(episode)))
    if (output := render_output(episode)) is not None:
        typer.echo("\n" + output)
    if episode.feedback:
        f = episode.feedback
        typer.echo(
            f"\nFeedback ({f.submitted_at:%Y-%m-%d %H:%M}, {f.reviewer or 'anonymous'}): "
            f"{f.verdict.value}; actual root cause {f.actual_root_cause or '-'}; {f.note or ''}"
        )


@app.command()
def feedback(
    episode_id: str,
    verdict: Annotated[Verdict, typer.Option(help="How the agent's top hypothesis held up.")],
    actual_root_cause: Annotated[
        str | None, typer.Option(help="The confirmed root cause, e.g. a failure mode ID.")
    ] = None,
    note: Annotated[str | None, typer.Option(help="Free-text context for the record.")] = None,
    reviewer: Annotated[str | None, typer.Option(help="Who reviewed it.")] = None,
) -> None:
    """Attach an expert's verdict to an episode."""
    request = FeedbackRequest(
        verdict=verdict, actual_root_cause=actual_root_cause, note=note, reviewer=reviewer
    )
    try:
        episode = platform().add_feedback(episode_id, request)
    except PlatformApiError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Feedback recorded on {episode.id}: {verdict.value}")


def main() -> None:
    app()
