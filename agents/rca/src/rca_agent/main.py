"""Entry point for the Foundry hosted agent (Responses protocol, port 8088).

The hosting library configures OpenTelemetry export, so this module doesn't. History is
managed by the hosting infrastructure, so responses aren't stored by the model service.
"""

from typing import TYPE_CHECKING, Any

from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity.aio import DefaultAzureCredential

from cs_platform.settings import PlatformSettings
from rca_agent.agent import create_agent

if TYPE_CHECKING:
    from agent_framework import Agent

_agent: Agent[Any] | None = None


async def agent_factory() -> Agent[Any]:
    """Build the agent once, inside the server's event loop, and reuse it."""
    global _agent
    if _agent is None:
        _agent = create_agent(
            PlatformSettings.from_env(), DefaultAzureCredential(), options={"store": False}
        )
    return _agent


def main() -> None:
    ResponsesHostServer(agent_factory).run()


if __name__ == "__main__":
    main()
