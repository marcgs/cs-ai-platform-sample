"""``csai``: the CS AI platform's command line."""

import asyncio
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from azure.identity.aio import DefaultAzureCredential

from cs_platform.episodes import Verdict  # noqa: TC001 - typer reads annotations at runtime
from cs_platform.eval_reporting import RunMetadata, write_artifacts
from cs_platform.evals import EvalCase, EvalSuite, RunOutput, assign_splits, run_suite
from cs_platform.settings import PlatformSettings, SettingsError
from cs_platform.telemetry import flush_telemetry
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


class EvalSplit(StrEnum):
    TRAIN = "train"
    TEST = "test"
    ALL = "all"


def describe(result: CaseResult) -> str:
    scores = " ".join(f"{name}={value:.2f}" for name, value in sorted(result.scores.items()))
    failure = result.output.failure
    error = f"  {failure.kind}:{failure.code}" if failure else ""
    return (
        f"{result.case_id:<10} repeat={result.repeat} "
        f"{result.output.duration_s:6.1f}s  {scores}{error}"
    )


def report(suite: EvalSuite, result: SuiteResult) -> list[str]:
    typer.echo(f"\n{suite.name}: {len(result.cases)} cases")
    metrics = result.gate_metrics
    intervals = result.gate_intervals
    for name, value in metrics.items():
        minimum = suite.thresholds.minimums.get(name)
        gate = f"  (min {minimum:.2f})" if minimum is not None else ""
        mark = "FAIL" if minimum is not None and value < minimum else "ok  "
        low, high = intervals[name]
        typer.echo(f"  {mark} {name:<20} {value:.2f}  95% CI [{low:.2f}, {high:.2f}]{gate}")
    for field, groups in result.groups.items():
        for label, scores in groups.items():
            values = " ".join(f"{name}={value:.2f}" for name, value in scores.items())
            typer.echo(f"  {field}={label} (informational): {values}")
    for warning in result.warnings(suite.thresholds):
        typer.echo(f"warning: {warning}", err=True)
    return result.failures(suite.thresholds)


def export_local_episodes(episodes: list[Episode], path: Path) -> None:
    """Write explicitly real local episodes, including legacy records, without overwriting."""
    records = [episode.model_dump(mode="json") for episode in episodes]
    if any(record.get("source", "real") != "real" for record in records):
        raise ValueError("Expected only real episodes")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps({**record, "source": "real"}) + "\n")


def make_target(
    entry: AgentEntry,
    target: TargetKind,
    credential: AsyncTokenCredential,
    *,
    episodes: list[Episode] | None = None,
) -> Target:
    if target is TargetKind.LOCAL:
        if episodes is not None:
            return local_target(
                entry, PlatformSettings.from_env(), credential, on_episode=episodes.append
            )
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
    entry: AgentEntry,
    suite: EvalSuite,
    target: TargetKind,
    concurrency: int,
    repeats: int = 1,
    *,
    episodes: list[Episode] | None = None,
) -> SuiteResult:
    async with DefaultAzureCredential() as credential:
        selected_target = (
            make_target(entry, target, credential)
            if episodes is None
            else make_target(entry, target, credential, episodes=episodes)
        )
        return await run_suite(
            suite,
            selected_target,
            concurrency=concurrency,
            repeats=repeats,
            on_result=lambda r: typer.echo(describe(r)),
        )


@app.command("eval")
def eval_command(
    agent: Annotated[str, typer.Argument(help=f"One of: {', '.join(AGENTS)}.")] = "rca",
    target: Annotated[TargetKind, typer.Option(help="Where the agent runs.")] = TargetKind.LOCAL,
    case: Annotated[list[str] | None, typer.Option(help="Run only these case IDs.")] = None,
    concurrency: Annotated[int, typer.Option(min=1, help="Cases run in parallel.")] = 3,
    repeats: Annotated[int, typer.Option(min=1, help="Independent runs per case.")] = 1,
    split: Annotated[
        EvalSplit, typer.Option(help="Machine-grouped evaluation split.")
    ] = EvalSplit.ALL,
    output: Annotated[Path | None, typer.Option(help="Write per-case results (JSONL).")] = None,
    agent_revision: Annotated[
        str | None, typer.Option(help="Evaluated agent revision, independent of harness revision.")
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(help="Model identity for run provenance (not model configuration)."),
    ] = None,
    episodes_output: Annotated[
        Path | None,
        typer.Option(
            "--episodes-output",
            "--episodes-jsonl",
            help="Export real local episodes to a new JSONL file.",
        ),
    ] = None,
    publish: Annotated[
        bool, typer.Option(help="Also score the run with Foundry's built-in evaluators.")
    ] = False,
) -> None:
    """Run the agent's eval suite and fail (exit 1) when a metric is below its threshold."""
    entry = agent_entry(agent)
    if episodes_output is not None and target is not TargetKind.LOCAL:
        raise typer.BadParameter("episode export requires --target local")
    if episodes_output is not None and episodes_output.exists():
        raise typer.BadParameter("episode output already exists")
    if output is not None and output.exists():
        raise typer.BadParameter("results output already exists")
    suite = entry.load_suite()
    if case and (unknown := set(case) - {item.id for item in suite.cases}):
        raise typer.BadParameter(
            f"unknown case IDs: {', '.join(sorted(unknown))}", param_hint="--case"
        )
    selected = tuple(
        item
        for item in assign_splits(suite.cases)
        if (not case or item.id in case) and (split is EvalSplit.ALL or item.split == split.value)
    )
    if not selected:
        raise typer.BadParameter("no cases selected", param_hint="--split/--case")
    suite = replace(suite, cases=selected)
    started_at = datetime.now(UTC)
    revision = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
        ).stdout.strip()
    )
    episodes: list[Episode] | None = [] if episodes_output is not None else None
    try:
        result = asyncio.run(
            evaluate(entry, suite, target, concurrency, repeats, episodes=episodes)
        )
    except SettingsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    if episodes_output is not None and episodes is not None:
        export_local_episodes(episodes, episodes_output)
    output = output or Path(".eval-results") / f"{started_at:%Y%m%d-%H%M%S-%f}" / "results.jsonl"
    write_artifacts(
        suite,
        result,
        output,
        RunMetadata(
            agent_revision=agent_revision
            or (revision if target is TargetKind.LOCAL else "unknown"),
            harness_revision=revision,
            harness_dirty=dirty,
            target=target.value,
            repeats=repeats,
            model=model
            or os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME")
            or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini"),
            started_at=started_at,
        ),
    )
    typer.echo(f"Results: {output} (HTML: {output.with_suffix('.html')})")
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
    typer.echo(
        "\nGate passed."
        if any(item.gated for item in result.cases)
        else "\nInformational run complete; no regression gate evaluated."
    )


# --- diagnose ------------------------------------------------------------------------------


@app.command()
def diagnose(
    incident: Annotated[str, typer.Argument(help='Machine and symptom, e.g. "M-0001: ...".')],
    agent: Annotated[str, typer.Option(help=f"One of: {', '.join(AGENTS)}.")] = "rca",
    target: Annotated[
        TargetKind, typer.Option(help="hosted (episode kept) or local (episode in memory).")
    ] = TargetKind.HOSTED,
    episodes_output: Annotated[
        Path | None,
        typer.Option(
            "--episodes-output",
            "--episodes-jsonl",
            help="Export this real local episode to a new JSONL file.",
        ),
    ] = None,
) -> None:
    """Ask an agent to diagnose an incident and print its report."""
    entry = agent_entry(agent)
    if episodes_output is not None and target is not TargetKind.LOCAL:
        raise typer.BadParameter("episode export requires --target local")
    if episodes_output is not None and episodes_output.exists():
        raise typer.BadParameter("episode output already exists")
    episodes: list[Episode] | None = [] if episodes_output is not None else None

    async def run() -> RunOutput:
        async with DefaultAzureCredential() as credential:
            case = EvalCase(id="adhoc", input=incident, expected={})
            selected_target = (
                make_target(entry, target, credential)
                if episodes is None
                else make_target(entry, target, credential, episodes=episodes)
            )
            return await selected_target(case)

    try:
        output = asyncio.run(run())
    except SettingsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    if episodes_output is not None and episodes is not None:
        export_local_episodes(episodes, episodes_output)
    typer.echo(entry.render(output.value) if output.value is not None else output.text or "")
    tools = ", ".join(output.tool_calls) or ("unavailable" if output.error else "none")
    typer.echo(f"\nTool calls: {tools}")
    if target is TargetKind.HOSTED:
        typer.echo(describe_correlation(output))
    if output.error:
        typer.echo(f"error: {output.error}", err=True)
        raise typer.Exit(1)


def describe_correlation(output: RunOutput) -> str:
    """Resolve only this response's episode, never a similar incident or session."""
    if not output.response_id or not output.episode_id:
        return "Episode: unavailable (host response identifier missing)"
    prefix = f"Response: {output.response_id}\nEpisode: {output.episode_id}"
    try:
        episode = PlatformClient.from_env().wait_for_episode(output.episode_id, output.response_id)
    except (SettingsError, PlatformApiError) as error:
        return f"{prefix} (unverified: {error})"
    if episode is None:
        return (
            f"{prefix} (unverified: episode not found; persistence may be delayed or failed; "
            f"check agent logs or retry `csai episodes show {output.episode_id}`)"
        )
    return f"{prefix} ({episode.status}, exact response verified)"


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
    try:
        app()
    finally:
        flush_telemetry()
