import runpy
from pathlib import Path
from typing import TYPE_CHECKING

from azure.ai.projects.models import AzureAISearchToolboxTool

if TYPE_CHECKING:
    import pytest


def test_search_description_survives_the_toolbox_payload_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIAGNOSTICS_MCP_ENDPOINT", "https://diagnostics.example/mcp")
    monkeypatch.setenv("AZURE_SEARCH_CONNECTION_ID", "diagnostics-search")
    monkeypatch.setenv("AZURE_SEARCH_INDEX_NAME", "diagnostics-cases")
    setup = runpy.run_path(str(Path(__file__).parents[3] / "scripts" / "setup_platform.py"))
    definition = setup["toolbox_definition"]()
    search = AzureAISearchToolboxTool(definition["tools"][1])
    assert search.description
    assert "historical diagnostic cases" in search.description
    assert search.as_dict() == definition["tools"][1]
    assert search.azure_ai_search.indexes[0].query_type == "vector_semantic_hybrid"
    assert definition["tools"][0]["type"] == "mcp"
