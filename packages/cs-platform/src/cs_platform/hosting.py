"""Exact hosted response identity, kept outside the agent's report and model options."""

from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_OID, uuid5

if TYPE_CHECKING:
    from agent_framework_foundry_hosting import HostedResponseRequest

HOSTED_RESPONSE_ID_OPTION = "cs_platform_hosted_response_id"


def hosted_episode_id(response_id: str) -> str:
    """Map a host-issued response ID to its episode's point-read key."""
    if not response_id or not response_id.strip():
        raise ValueError("A hosted response ID is required")
    return uuid5(NAMESPACE_OID, f"cs-platform:hosted-response:{response_id}").hex


def prepare_episode_options(
    request: HostedResponseRequest, options: dict[str, Any]
) -> dict[str, Any]:
    """Bind this invocation to the host's ID, never a caller's generation option."""
    return {**options, HOSTED_RESPONSE_ID_OPTION: request.response_id}
