"""The agents the CLI knows, and targets that run an eval case against one of them.

- ``local``: builds the agent in-process with the platform harness (model and toolbox in
  Foundry, episodes in memory). Tests code and instruction changes before deploying.
- ``hosted``: calls the deployed hosted agent's Responses endpoint. Tests what's live.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from azure.identity.aio import get_bearer_token_provider
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from cs_platform.capture import EPISODE_ID_KEY
from cs_platform.episodes import InMemoryEpisodeStore
from cs_platform.evals import RunOutput
from cs_platform.telemetry import configure_telemetry
from rca_agent.agent import create_agent
from rca_agent.local import render
from rca_agent.report import RcaReport
from rca_evals import load_suite

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent_framework import Agent
    from azure.core.credentials_async import AsyncTokenCredential

    from cs_platform.evals import EvalCase, EvalSuite, Target
    from cs_platform.settings import PlatformSettings

AI_SCOPE = "https://ai.azure.com/.default"


class HostedRunError(RuntimeError):
    pass


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
    entry: AgentEntry, settings: PlatformSettings, credential: AsyncTokenCredential
) -> Target:
    configure_telemetry(settings, service_name=f"{entry.service}-local")

    async def run(case: EvalCase) -> RunOutput:
        store = InMemoryEpisodeStore()
        async with entry.create(settings, credential, store=store) as agent:
            response = await agent.run(case.input)
        episode_id = response.additional_properties.get(EPISODE_ID_KEY)
        episode = await store.get(episode_id) if isinstance(episode_id, str) else None
        value = response.value
        return RunOutput(
            text=response.text,
            value=value
            if isinstance(value, entry.output_type)
            else parse(entry.output_type, response.text),
            tool_calls=[call.name for call in episode.tool_calls] if episode else [],
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
        if response.status != "completed" or response.error is not None:
            # Failed runs (e.g. the model rate-limited inside the agent) don't raise.
            detail = response.error or response.incomplete_details
            raise HostedRunError(f"response {response.id} {response.status}: {detail}")
        text = response.output_text
        return RunOutput(
            text=text,
            value=parse(entry.output_type, text),
            tool_calls=[
                getattr(item, "name", item.type)
                for item in response.output
                if item.type in {"function_call", "mcp_call"}
            ],
        )

    return run
