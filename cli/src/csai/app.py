"""``csai``: the CS AI platform's command line."""

import asyncio
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path  # noqa: TC003 - typer reads annotations at runtime
from typing import TYPE_CHECKING, Annotated

import typer
from azure.identity.aio import DefaultAzureCredential

from cs_platform.episodes import Verdict  # noqa: TC001 - typer reads annotations at runtime
from cs_platform.evals import EvalCase, EvalSuite, RunOutput, run_suite
from cs_platform.settings import PlatformSettings, SettingsError
from csai import foundry
from csai.environment import load_environment
from csai.platform import PlatformApiError, PlatformClient
from csai.targets import AGENTS, hosted_target, local_target
from platform_api.api import FeedbackRequest

if TYPE_CHECKING:
    from azure.core.credentials_async import AsyncTokenCredential

    from cs_platform.episodes import Episode
    from cs_platform.evals import CaseResult, SuiteResult, Target
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


def make_target(entry: AgentEntry, target: TargetKind, credential: AsyncTokenCredential) -> Target:
    if target is TargetKind.LOCAL:
        return local_target(entry, PlatformSettings.from_env(), credential)
    endpoint = os.environ.get(entry.responses_endpoint_variable)
    if not endpoint:
        raise SettingsError(f"{entry.responses_endpoint_variable} is not set; deploy first")
    return hosted_target(entry, endpoint, credential)


def agent_entry(agent: str) -> AgentEntry:
    entry = AGENTS.get(agent)
    if entry is None:
        raise typer.BadParameter(f"unknown agent {agent!r}", param_hint="AGENT")
    return entry


async def evaluate(
    entry: AgentEntry, suite: EvalSuite, target: TargetKind, concurrency: int
) -> SuiteResult:
    async with DefaultAzureCredential() as credential:
        return await run_suite(
            suite,
            make_target(entry, target, credential),
            concurrency=concurrency,
            on_result=lambda r: typer.echo(describe(r)),
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
    entry = agent_entry(agent)
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


# --- diagnose ------------------------------------------------------------------------------


@app.command()
def diagnose(
    incident: Annotated[str, typer.Argument(help='Machine and symptom, e.g. "M-0001: ...".')],
    agent: Annotated[str, typer.Option(help=f"One of: {', '.join(AGENTS)}.")] = "rca",
    target: Annotated[
        TargetKind, typer.Option(help="hosted (episode kept) or local (episode in memory).")
    ] = TargetKind.HOSTED,
) -> None:
    """Ask an agent to diagnose an incident and print its report."""
    entry = agent_entry(agent)
    started = datetime.now(UTC)

    async def run() -> RunOutput:
        async with DefaultAzureCredential() as credential:
            case = EvalCase(id="adhoc", input=incident, expected={})
            return await make_target(entry, target, credential)(case)

    try:
        output = asyncio.run(run())
    except SettingsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(entry.render(output.value) if output.value is not None else output.text or "")
    tools = ", ".join(output.tool_calls) or "none"
    typer.echo(f"\nTool calls: {tools}")
    if target is TargetKind.HOSTED:
        episode = find_episode(entry.service, incident, since=started)
        typer.echo(f"Episode: {episode or 'not found yet; see `csai episodes list`'}")


def find_episode(agent: str, incident: str, *, since: datetime) -> str | None:
    """The hosted run's episode: the newest one for this input recorded since ``since``."""
    try:
        recent = PlatformClient.from_env().list_episodes(agent=agent, limit=10)
    except SettingsError, PlatformApiError:
        return None
    matches = [e for e in recent if e.input == incident and e.created_at >= since]
    return matches[0].id if matches else None


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
    entry = next((e for e in AGENTS.values() if e.service == episode.agent), None)
    if episode.output is not None and entry is not None:
        typer.echo("\n" + entry.render(entry.output_type.model_validate(episode.output)))
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
