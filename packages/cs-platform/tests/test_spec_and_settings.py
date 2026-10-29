from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from cs_platform.settings import PlatformSettings, SettingsError
from cs_platform.spec import load_spec

if TYPE_CHECKING:
    from pathlib import Path


def test_load_spec_resolves_files(tmp_path: Path) -> None:
    (tmp_path / "instructions.md").write_text("  Be precise.\n", encoding="utf-8")
    (tmp_path / "agent.spec.yaml").write_text(
        "name: rca-agent\nversion: 0.1.0\ndescription: RCA\n"
        "instructions: instructions.md\ntools: [diagnostics]\neval_suite: evals\n",
        encoding="utf-8",
    )
    spec = load_spec(tmp_path / "agent.spec.yaml")
    assert spec.instructions == "Be precise."
    assert spec.tools == ("diagnostics",)
    assert spec.eval_suite == (tmp_path / "evals").resolve()


def test_spec_rejects_invalid_names(tmp_path: Path) -> None:
    (tmp_path / "i.md").write_text("x", encoding="utf-8")
    (tmp_path / "s.yaml").write_text(
        "name: Not Valid\nversion: 1\ndescription: d\ninstructions: i.md\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        load_spec(tmp_path / "s.yaml")


def test_settings_require_project_endpoint() -> None:
    with pytest.raises(SettingsError):
        PlatformSettings.from_env({})


def test_settings_read_optional_values() -> None:
    settings = PlatformSettings.from_env(
        {
            "FOUNDRY_PROJECT_ENDPOINT": "https://example/api/projects/p",
            "FOUNDRY_MODEL_DEPLOYMENT_NAME": "chat",
            "COSMOS_ENDPOINT": "https://cosmos.example",
            "TOOLBOX_ENDPOINT": "",
        }
    )
    assert settings.model_deployment == "chat"
    assert settings.cosmos_endpoint == "https://cosmos.example"
    assert settings.toolbox_endpoint is None
    assert settings.cosmos_database == "cs-platform"
