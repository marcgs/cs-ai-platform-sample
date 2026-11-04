"""Reproduce the deployed hosting adapter's snapshot handling without a model."""

import asyncio
import json
from importlib.metadata import version

from agent_framework import AgentResponse, AgentResponseUpdate, Content
from agent_framework_foundry_hosting._responses import _OutputItemTracker
from azure.ai.agentserver.responses.aio.streaming import ResponseEventStream


async def reproduce() -> dict[str, object]:
    """Compare the real hosting adapter with the framework's final aggregation."""
    stream = ResponseEventStream(response_id="offline-snapshot-reproduction")
    stream.emit_created()
    stream.emit_in_progress()
    tracker = _OutputItemTracker(stream)
    arguments = '{"machine_id":"M-0001"}'
    contents = [
        Content.from_function_call(
            call_id="call-1",
            name="get_machine_context",
            arguments=arguments,
            merge_mode="append",
        ),
        Content.from_function_call(
            call_id="call-1",
            name="get_machine_context",
            arguments=arguments,
            merge_mode="replace",
        ),
        Content.from_usage(
            {"input_token_count": 100, "output_token_count": 10},
            merge_mode="replace",
        ),
        Content.from_usage(
            {"input_token_count": 250, "output_token_count": 25},
            merge_mode="replace",
        ),
    ]
    events = []
    for content in contents:
        events.extend([event async for event in tracker.handle(content)])
    events.extend(tracker.close())
    response = AgentResponse.from_updates(
        [AgentResponseUpdate(message_id="turn-1", contents=[content]) for content in contents]
    )
    return {
        "hosting_version": version("agent-framework-foundry-hosting"),
        "host_usage": tracker.usage,
        "host_arguments": [
            event["arguments"]
            for event in events
            if event["type"] == "response.function_call_arguments.done"
        ],
        "final_usage": response.usage_details,
        "final_arguments": [
            content.arguments
            for message in response.messages
            for content in message.contents
            if content.type == "function_call"
        ],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(reproduce()), indent=2))
