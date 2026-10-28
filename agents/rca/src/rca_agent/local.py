"""Run the RCA agent locally against a direct MCP server (e.g. ``func start``).

    uv run rca-local "M-0001: overlay getting worse, stage temperature alarm this morning"

Reads settings from the environment and a ``.env`` file in the working directory. Needs a
model deployment (``FOUNDRY_PROJECT_ENDPOINT``) and a tool source (``DIAGNOSTICS_MCP_URL``).
Episodes go to Cosmos DB when ``COSMOS_ENDPOINT`` is set, otherwise they're kept in memory.
"""

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Any

from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from cs_platform.capture import EPISODE_ID_KEY
from cs_platform.episodes import InMemoryEpisodeStore
from cs_platform.factory import episode_store
from cs_platform.settings import PlatformSettings, SettingsError
from cs_platform.telemetry import configure_telemetry
from rca_agent.agent import create_agent
from rca_agent.report import RcaReport

if TYPE_CHECKING:
    from cs_platform.episodes import Episode, EpisodeStore


def render(report: RcaReport) -> str:
    lines = [f"Machine {report.machine_id}", "", report.summary, ""]
    for h in report.hypotheses:
        lines.append(f"{h.rank}. {h.title} [{h.failure_mode_id}] confidence {h.confidence:.2f}")
        lines.append(f"   {h.root_cause}")
        lines.extend(f"   - {e.ref}: {e.excerpt}" for e in h.evidence)
        lines.extend(f"   check: {c}" for c in h.recommended_checks)
        lines.append("")
    if report.missing_information:
        lines.append("Missing information:")
        lines.extend(f" - {item}" for item in report.missing_information)
    return "\n".join(lines)


def render_episode(episode: Episode) -> str:
    calls = ", ".join(f"{c.name}({c.duration_ms:.0f} ms)" for c in episode.tool_calls)
    usage = episode.usage
    tokens = f"{usage.input_tokens} in / {usage.output_tokens} out" if usage else "n/a"
    return (
        f"Episode {episode.id} ({episode.status}), trace {episode.trace_id or 'n/a'}\n"
        f"Tool calls: {calls or 'none'}\nTokens: {tokens}"
    )


async def episode_summary(store: EpisodeStore, episode_id: str) -> str:
    """Render the run's episode; capture is best-effort, so a missing one doesn't fail the run."""
    try:
        return render_episode(await store.get(episode_id))
    except Exception as error:
        return f"Episode {episode_id} not available: {type(error).__name__}: {error}"


async def run(incident: str) -> int:
    settings = PlatformSettings.from_env()
    configure_telemetry(settings, service_name="rca-agent-local")
    async with DefaultAzureCredential() as credential:
        store: EpisodeStore = episode_store(settings, credential)
        # The agent owns its tool connections; close them in the task that opened them.
        async with create_agent(settings, credential, store=store) as agent:
            response: Any = await agent.run(incident)

        report = response.value
        print(render(report) if isinstance(report, RcaReport) else response.text)
        episode_id = response.additional_properties.get(EPISODE_ID_KEY)
        if episode_id:
            print("\n" + await episode_summary(store, episode_id))
            if isinstance(store, InMemoryEpisodeStore):
                print("(in-memory store: set COSMOS_ENDPOINT to keep episodes)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the RCA agent locally against a direct MCP server."
    )
    parser.add_argument("incident", help="Machine ID and symptom, as a field engineer reports it.")
    args = parser.parse_args()
    load_dotenv()
    try:
        sys.exit(asyncio.run(run(args.incident)))
    except SettingsError as error:
        sys.exit(f"Configuration error: {error}")


if __name__ == "__main__":
    main()
