import json
from typing import TYPE_CHECKING, Any

import pytest
from agent_framework import FunctionTool, tool

from cs_platform.episodes import Episode, InMemoryEpisodeStore
from cs_platform.evidence import Evidence
from cs_platform.settings import PlatformSettings, SettingsError
from cs_platform.testing import ScriptedChatClient, call, text
from diagnostics_domain.dataset import load_seed
from diagnostics_mcp.tools import TOOL_NAMES, DiagnosticsTools, telemetry_ref
from rca_agent import main as hosted
from rca_agent.agent import create_agent, load_rca_spec
from rca_agent.local import episode_summary, render
from rca_agent.report import RcaReport

if TYPE_CHECKING:
    from azure.core.credentials_async import AsyncTokenCredential

SETTINGS = PlatformSettings(foundry_project_endpoint="https://example/api/projects/p")
CREDENTIAL: AsyncTokenCredential = None  # type: ignore[assignment]  # unused with injected parts


def diagnostics_function_tools() -> list[FunctionTool]:
    """The real MCP tool logic over the seed data, as in-process function tools."""
    impl = DiagnosticsTools.from_seed()

    @tool
    def get_error_events(machine_id: str, hours: int = 72) -> str:
        """Error events in a look-back window."""
        return impl.error_events(machine_id, hours).model_dump_json()

    @tool
    def get_telemetry_window(machine_id: str, signal: str, hours: int = 72) -> str:
        """Telemetry summary for one signal."""
        return impl.telemetry_window(machine_id, signal, hours).model_dump_json()

    @tool
    def get_logbook(machine_id: str, days: int = 30) -> str:
        """Service logbook entries."""
        return impl.logbook(machine_id, days).model_dump_json()

    return [get_error_events, get_telemetry_window, get_logbook]


def test_spec_is_packaged_with_instructions() -> None:
    spec = load_rca_spec()
    assert spec.name == "rca-agent"
    assert spec.tools == ("diagnostics",)
    assert spec.eval_suite is not None
    assert spec.eval_suite.parts[-2:] == ("evals", "rca")


def test_instructions_name_every_diagnostics_tool() -> None:
    instructions = load_rca_spec().instructions
    for name in TOOL_NAMES:
        assert f"`{name}`" in instructions, name


@pytest.mark.parametrize("knowledge", ["unavailable", "relevant", "irrelevant", "empty", "failed"])
async def test_golden_path_produces_an_evidence_backed_report(knowledge: str) -> None:
    data = load_seed()
    scenario = data.scenario("SC-001")
    mode = data.failure_mode(scenario.expected_failure_mode)
    signal = mode.signature.signal
    machine = scenario.machine_id
    fault_event = next(
        e for e in data.events_for(machine, start=scenario.onset) if e.code in mode.error_codes
    )
    clue = next(e for e in data.logbook_for(machine) if e.text in mode.logbook_clues)
    report = {
        "machine_id": machine,
        "summary": f"{mode.name} is the most likely cause.",
        "hypotheses": [
            {
                "rank": 1,
                "failure_mode_id": mode.id,
                "title": mode.name,
                "root_cause": mode.root_cause,
                "confidence": 0.8,
                "evidence": [
                    {"source": "get_error_events", "ref": fault_event.id, "excerpt": "Fault."},
                    {
                        "source": "get_telemetry_window",
                        "ref": telemetry_ref(machine, signal),
                        "excerpt": "Signal out of tolerance.",
                    },
                    {"source": "get_logbook", "ref": clue.id, "excerpt": "Recent maintenance."},
                ],
                "recommended_checks": list(mode.recommended_checks),
            }
        ],
        "missing_information": [],
    }
    structured = RcaReport.model_validate(report)
    history = [
        case
        for case in data.historical_cases
        if (case.confirmed_failure_mode == mode.id) == (knowledge == "relevant")
    ][:1]

    @tool
    def azure_ai_search(query: str) -> str:
        """Historical diagnostic cases matching the incident symptom and subsystem."""
        if knowledge == "failed":
            raise ConnectionError("Historical-case search is temporarily unavailable.")
        return json.dumps([case.model_dump(mode="json") for case in history])

    turns = [
        [call("get_error_events", machine_id=machine, hours=168)],
        [call("get_telemetry_window", "call-2", machine_id=machine, signal=signal, hours=168)],
        [call("get_logbook", "call-3", machine_id=machine)],
    ]
    tools = diagnostics_function_tools()
    if knowledge != "unavailable":
        tools.append(azure_ai_search)
        turns.append(
            [call("azure_ai_search", "call-4", query=f"{scenario.symptom} {mode.subsystem}")]
        )
    if knowledge == "empty":
        history = []
    if knowledge == "relevant":
        structured.hypotheses[0].evidence.append(
            Evidence(
                source="azure_ai_search",
                ref=history[0].id,
                excerpt=history[0].resolution,
            )
        )
    elif knowledge == "unavailable":
        structured.missing_information.append("Historical-case search is unavailable.")
    elif knowledge == "failed":
        structured.missing_information.append("Historical-case search failed.")
    else:
        structured.missing_information.append("No relevant historical case was found.")
    turns.append([text(structured.model_dump_json())])
    client = ScriptedChatClient(turns)
    store = InMemoryEpisodeStore()
    agent = create_agent(SETTINGS, CREDENTIAL, client=client, store=store, tools=tools)

    response: Any = await agent.run(f"{machine}: {scenario.symptom}")

    assert isinstance(response.value, RcaReport)
    [episode] = await store.list()
    assert episode.status == "succeeded"
    expected_calls = [
        "get_error_events",
        "get_telemetry_window",
        "get_logbook",
    ]
    if knowledge != "unavailable":
        expected_calls.append("azure_ai_search")
    assert [c.name for c in episode.tool_calls] == expected_calls
    tool_output = " ".join(c.result or "" for c in episode.tool_calls)
    cited = [e.ref for h in response.value.hypotheses for e in h.evidence]
    assert all(ref in tool_output for ref in cited), "every cited ref comes from a tool result"
    assert any(ref.startswith("HC-") for ref in cited) == (knowledge == "relevant")
    if knowledge != "relevant":
        assert response.value.missing_information
    if knowledge == "irrelevant":
        assert history[0].id in tool_output
        assert history[0].id not in cited
    if knowledge == "failed":
        assert episode.tool_calls[-1].error
    assert response.value.hypotheses[0].failure_mode_id == scenario.expected_failure_mode


def test_agent_needs_a_tool_source() -> None:
    with pytest.raises(SettingsError, match="DIAGNOSTICS_MCP_URL"):
        create_agent(
            SETTINGS, CREDENTIAL, client=ScriptedChatClient([]), store=InMemoryEpisodeStore()
        )


def test_hosting_server_accepts_the_factory() -> None:
    # The server validates the factory's signature, evaluating its annotations at runtime.
    from agent_framework_foundry_hosting._agent_source import validate_agent_source

    validate_agent_source(hosted.agent_factory)


async def test_hosted_factory_builds_the_agent_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p"
    )
    monkeypatch.setenv("DIAGNOSTICS_MCP_URL", "http://localhost:7071/runtime/webhooks/mcp")
    monkeypatch.setattr(hosted, "_agent", None)
    first = await hosted.agent_factory()
    assert first is await hosted.agent_factory()
    assert first.name == "rca-agent"


def test_render_shows_ranked_hypotheses_with_refs() -> None:
    report = RcaReport.model_validate(
        {
            "machine_id": "M-0001",
            "summary": "Cooling drift.",
            "hypotheses": [
                {
                    "rank": 1,
                    "failure_mode_id": "FM-01",
                    "title": "Stage cooling drift",
                    "root_cause": "Valve.",
                    "confidence": 0.75,
                    "evidence": [{"source": "s", "ref": "EV-000001", "excerpt": "x"}],
                    "recommended_checks": ["Check flow."],
                }
            ],
            "missing_information": ["Flow rate"],
        }
    )
    output = render(report)
    assert "1. Stage cooling drift [FM-01] confidence 0.75" in output
    assert "EV-000001" in output
    assert "Flow rate" in output


async def test_episode_summary_survives_a_store_outage() -> None:
    class UnreachableStore(InMemoryEpisodeStore):
        async def get(self, episode_id: str) -> Episode:
            raise ConnectionError("store down")

    summary = await episode_summary(UnreachableStore(), "abc123")
    assert summary == "Episode abc123 not available: ConnectionError: store down"
