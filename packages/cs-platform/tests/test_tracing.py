import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest
from agent_framework import MCPStreamableHTTPTool
from agent_framework.observability import ChatTelemetryLayer
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from opentelemetry import propagate, trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import StatusCode

from cs_platform.episodes import InMemoryEpisodeStore
from cs_platform.factory import build_agent
from cs_platform.testing import ScriptedChatClient, call, text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from cs_platform.spec import AgentSpec


class TracedChatClient(ChatTelemetryLayer, ScriptedChatClient):  # pyright: ignore[reportIncompatibleMethodOverride]
    pass


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    yield exporter
    provider.shutdown()


@pytest.mark.parametrize("stream", [False, True])
async def test_episode_parents_agent_model_and_tool_spans(
    spec: AgentSpec, spans: InMemorySpanExporter, stream: bool
) -> None:
    async def backend(request: httpx.Request) -> httpx.Response:
        with trace.get_tracer(__name__).start_as_current_span(
            "diagnostic.backend",
            context=propagate.extract(dict(request.headers)),
            kind=trace.SpanKind.SERVER,
        ):
            return httpx.Response(200, text="evidence")

    async def diagnostic_tool() -> str:
        """Return synthetic diagnostic evidence."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
            HTTPXClientInstrumentor.instrument_client(client)
            return (await client.get("https://example.test/diagnostics")).text

    store = InMemoryEpisodeStore()
    agent = build_agent(
        spec,
        client=TracedChatClient([[call("diagnostic_tool")], [text("done")]]),
        store=store,
        tools=[diagnostic_tool],
    )
    with trace.get_tracer(__name__).start_as_current_span("request") as parent:
        if stream:
            response = agent.run("check", stream=True)
            # Deliberately consume from another task, as a streaming host can do.
            await asyncio.create_task(response.get_final_response())
        else:
            await agent.run("check")
        assert trace.get_current_span() is parent

    [episode] = await store.list()
    exported = spans.get_finished_spans()
    root = next(s for s in exported if s.name == "cs_platform.episode")
    assert root.context is not None
    assert root.parent == parent.get_span_context()
    assert root.attributes is not None
    assert root.attributes["cs_platform.episode_id"] == episode.id
    assert episode.trace_id == f"{root.context.trace_id:032x}"
    assert episode.status == "succeeded"
    assert root.end_time is not None
    assert root.start_time is not None
    descendants = {s.context.span_id: s for s in exported if s.context is not None}
    for span in exported:
        assert span.context is not None
        assert span.context.trace_id == root.context.trace_id
        if span.name not in {"request", "cs_platform.episode"}:
            assert span.parent is not None
            ancestor = span
            while ancestor.parent != root.context:
                assert ancestor.parent is not None
                ancestor = descendants[ancestor.parent.span_id]
            assert span.end_time is not None
            assert span.start_time is not None
            assert root.start_time <= span.start_time <= span.end_time <= root.end_time
    assert any(s.name == "diagnostic.backend" for s in exported)
    backend_span = next(s for s in exported if s.name == "diagnostic.backend")
    assert backend_span.parent is not None
    assert descendants[backend_span.parent.span_id].kind == trace.SpanKind.CLIENT
    assert any(s.name.startswith("chat ") for s in exported)
    assert any(s.name.startswith("invoke_agent ") for s in exported)
    for model in (s for s in exported if s.name.startswith("chat ")):
        assert model.parent is not None
        assert descendants[model.parent.span_id].name.startswith("invoke_agent ")
    assert not trace.get_current_span().get_span_context().is_valid


@pytest.mark.parametrize("stream", [False, True])
async def test_failed_run_keeps_real_trace_and_ends_span(
    spec: AgentSpec, spans: InMemorySpanExporter, stream: bool
) -> None:
    store = InMemoryEpisodeStore()
    agent = build_agent(spec, client=ScriptedChatClient([]), store=store)
    result = agent.run("check", stream=True).get_final_response() if stream else agent.run("check")
    with pytest.raises(IndexError):
        await result
    [episode] = await store.list()
    root = next(s for s in spans.get_finished_spans() if s.name == "cs_platform.episode")
    assert root.context is not None
    assert episode.trace_id == f"{root.context.trace_id:032x}"
    assert episode.status == "failed"
    assert root.status.status_code == StatusCode.ERROR
    exceptions = [event for event in root.events if event.name == "exception"]
    assert len(exceptions) == 1
    assert exceptions[0].attributes is not None
    assert exceptions[0].attributes["exception.type"] == "IndexError"
    assert root.end_time is not None
    assert not trace.get_current_span().get_span_context().is_valid


@pytest.mark.parametrize("stream", [False, True])
async def test_tool_error_is_exported_in_the_episode_trace(
    spec: AgentSpec, spans: InMemorySpanExporter, stream: bool
) -> None:
    def diagnostic_tool() -> str:
        """Fail to retrieve synthetic evidence."""
        raise RuntimeError("diagnostic backend unavailable")

    store = InMemoryEpisodeStore()
    agent = build_agent(
        spec,
        client=TracedChatClient([[call("diagnostic_tool")], [text("cannot diagnose")]]),
        store=store,
        tools=[diagnostic_tool],
    )
    if stream:
        await agent.run("check", stream=True).get_final_response()
    else:
        await agent.run("check")
    [episode] = await store.list()
    failed = [s for s in spans.get_finished_spans() if s.status.status_code == StatusCode.ERROR]
    assert failed
    assert episode.tool_calls[0].error is not None
    assert all(
        s.context is not None and f"{s.context.trace_id:032x}" == episode.trace_id for s in failed
    )


async def test_closing_stream_ends_episode_span(
    spec: AgentSpec, spans: InMemorySpanExporter
) -> None:
    store = InMemoryEpisodeStore()
    agent = build_agent(spec, client=TracedChatClient([[text("partial")]]), store=store)
    stream = agent.run("check", stream=True)
    await anext(stream)
    await stream.close()
    [episode] = await store.list()
    root = next(s for s in spans.get_finished_spans() if s.name == "cs_platform.episode")
    assert episode.completed_at is not None
    assert root.end_time is not None
    assert not trace.get_current_span().get_span_context().is_valid


@pytest.mark.parametrize("stream", [False, True])
async def test_real_mcp_session_propagates_episode_context_in_metadata(
    spec: AgentSpec, spans: InMemorySpanExporter, stream: bool
) -> None:
    server = FastMCP("diagnostics")

    @server.tool()
    def diagnostic_tool(ctx: Context) -> str:
        """Return synthetic evidence from a real in-memory MCP server."""
        meta = ctx.request_context.meta
        assert meta is not None
        with trace.get_tracer(__name__).start_as_current_span(
            "mcp.server.diagnostic",
            context=propagate.extract(meta.model_dump()),
            kind=trace.SpanKind.SERVER,
        ):
            return "evidence"

    store = InMemoryEpisodeStore()
    async with (
        create_connected_server_and_client_session(server) as session,
        MCPStreamableHTTPTool(
            "diagnostics", "https://example.test/mcp", session=session, load_prompts=False
        ) as mcp_tool,
    ):
        agent = build_agent(
            spec,
            client=TracedChatClient([[call("diagnostic_tool")], [text("done")]]),
            store=store,
            tools=[mcp_tool],
        )
        if stream:
            await agent.run("check", stream=True).get_final_response()
        else:
            await agent.run("check")

    [episode] = await store.list()
    exported = spans.get_finished_spans()
    backend = next(s for s in exported if s.name == "mcp.server.diagnostic")
    assert backend.context is not None
    assert f"{backend.context.trace_id:032x}" == episode.trace_id
    assert backend.parent is not None
    parent = next(
        s
        for s in exported
        if s.context is not None
        and s.context.span_id == backend.parent.span_id
        and s.context.trace_id == backend.parent.trace_id
    )
    assert parent.name.startswith("execute_tool ")
