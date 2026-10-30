"""The agents the CLI knows, and targets that run an eval case against one of them.

- ``local``: builds the agent in-process with the platform harness (model and toolbox in
  Foundry, episodes in memory). Tests code and instruction changes before deploying.
- ``hosted``: calls the deployed hosted agent's Responses endpoint. Tests what's live.
"""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from azure.identity.aio import get_bearer_token_provider
from openai import AsyncOpenAI
from pydantic import BaseModel, TypeAdapter, ValidationError

from cs_platform.capture import EPISODE_ID_KEY
from cs_platform.episodes import InMemoryEpisodeStore, ToolCall
from cs_platform.evals import RunError, RunOutput
from cs_platform.hosting import hosted_episode_id
from cs_platform.settings import SettingsError
from cs_platform.telemetry import configure_telemetry
from csai.platform import PlatformApiError, PlatformClient
from rca_agent.agent import create_agent
from rca_agent.local import render
from rca_agent.report import RcaReport
from rca_evals import load_suite

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent_framework import Agent
    from azure.core.credentials_async import AsyncTokenCredential

    from cs_platform.episodes import Episode
    from cs_platform.evals import EvalCase, EvalSuite, Target
    from cs_platform.settings import PlatformSettings

AI_SCOPE = "https://ai.azure.com/.default"


@dataclass(frozen=True)
class AgentEntry:
    service: str
    """The azd service name; azd records the deployed endpoints under AGENT_<SERVICE>_*."""
    create: Callable[..., Agent[Any]]
    output_type: type[BaseModel]
    load_suite: Callable[[], EvalSuite]
    render: Callable[[Any], str]
    """Formats a structured output for the terminal."""

    @property
    def responses_endpoint_variable(self) -> str:
        return f"AGENT_{self.service.upper().replace('-', '_')}_RESPONSES_ENDPOINT"


AGENTS = {"rca": AgentEntry("rca-agent", create_agent, RcaReport, load_suite, render)}


def parse(output_type: type[BaseModel], text: str | None) -> BaseModel | None:
    if not text:
        return None
    try:
        return output_type.model_validate_json(text)
    except ValidationError:
        return None


def local_target(
    entry: AgentEntry,
    settings: PlatformSettings,
    credential: AsyncTokenCredential,
    *,
    on_episode: Callable[[Episode], None] | None = None,
) -> Target:
    configure_telemetry(settings, service_name=f"{entry.service}-local")

    async def run(case: EvalCase) -> RunOutput:
        store = InMemoryEpisodeStore()
        try:
            async with entry.create(settings, credential, store=store) as agent:
                response = await agent.run(case.input)
        except Exception as error:
            episodes = await store.list(limit=1)
            episode = episodes[0] if episodes else None
            if episode is not None and on_episode is not None:
                on_episode(episode)
            return RunOutput(
                error=f"{type(error).__name__}: {error}",
                tool_trace=episode.tool_calls if episode else [],
                tool_calls=[call.name for call in episode.tool_calls] if episode else [],
                tool_trace_complete=episode is not None and not episode.truncated,
                episode_id=episode.id if episode else None,
            )
        episode_id = response.additional_properties.get(EPISODE_ID_KEY)
        episode = await store.get(episode_id) if isinstance(episode_id, str) else None
        if episode is not None and on_episode is not None:
            on_episode(episode)
        try:
            value = response.value
        except ValidationError:
            value = None
        parsed = (
            value
            if isinstance(value, entry.output_type)
            else parse(entry.output_type, response.text)
        )
        return RunOutput(
            text=response.text,
            value=parsed,
            tool_calls=[call.name for call in episode.tool_calls] if episode else [],
            tool_trace=episode.tool_calls if episode else [],
            tool_trace_complete=episode is not None and not episode.truncated,
            failure=(
                RunError(kind="unparseable", code="invalid_output")
                if parsed is None and response.text
                else None
            ),
            episode_id=episode.id if episode else None,
        )

    return run


def hosted_target(entry: AgentEntry, endpoint: str, credential: AsyncTokenCredential) -> Target:
    client = AsyncOpenAI(
        base_url=endpoint.split("/responses", 1)[0],
        default_query={"api-version": "v1"},
        api_key=get_bearer_token_provider(credential, AI_SCOPE),
    )

    async def run(case: EvalCase) -> RunOutput:
        response = await client.responses.create(input=case.input)
        response_id = response.id if response.id and response.id.strip() else None
        episode_id = hosted_episode_id(response_id) if response_id else None
        episode = None
        if response_id and episode_id:
            with suppress(SettingsError, PlatformApiError):
                episode = await asyncio.to_thread(
                    lambda: PlatformClient.from_env().wait_for_episode(episode_id, response_id)
                )
        if response.status != "completed" or response.error is not None:
            # Failed runs (e.g. the model rate-limited inside the agent) don't raise.
            detail = response.error or response.incomplete_details
            return RunOutput(
                error=f"response {response.id} {response.status}: {detail}",
                response_id=response_id,
                episode_id=episode_id,
                tool_calls=[call.name for call in episode.tool_calls] if episode else [],
                tool_trace=episode.tool_calls if episode else [],
                tool_trace_complete=episode is not None and not episode.truncated,
            )
        text = response.output_text
        value = parse(entry.output_type, text)
        trace: list[ToolCall] = []
        for item in response.output:
            if item.type not in {"function_call", "mcp_call"}:
                continue
            details = item.model_dump()
            arguments = details.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {"unparsed": arguments}
            trace.append(
                ToolCall(
                    name=str(details.get("name", item.type)),
                    arguments=(
                        TypeAdapter(dict[str, Any]).validate_python(arguments)
                        if isinstance(arguments, dict)
                        else {"value": arguments}
                    ),
                    result=str(details["output"]) if details.get("output") is not None else None,
                    started_at=datetime.now(UTC),
                    duration_ms=0,
                )
            )
        return RunOutput(
            response_id=response_id,
            episode_id=episode_id,
            text=text,
            value=value,
            failure=(
                RunError(kind="unparseable", code="invalid_output")
                if value is None and text
                else None
            ),
            tool_trace=episode.tool_calls if episode else trace,
            tool_trace_complete=episode is not None and not episode.truncated,
            tool_calls=[call.name for call in episode.tool_calls]
            if episode
            else [
                getattr(item, "name", item.type)
                for item in response.output
                if item.type in {"function_call", "mcp_call"}
            ],
        )

    return run
