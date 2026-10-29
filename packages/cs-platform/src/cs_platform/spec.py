"""Agent specs: an agent is declared, not hand-wired.

An ``agent.spec.yaml`` next to the agent's code names the agent, points to its instructions
and evaluation suite, and lists the tool sources it needs::

    name: rca-agent
    version: 0.1.0
    description: Ranks root-cause hypotheses for a machine incident.
    instructions: instructions.md
    tools: [diagnostics]
    eval_suite: ../../evals/rca
"""

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field


class AgentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    version: str
    description: str
    instructions: str
    """Instruction text, resolved from the file named in the spec."""
    tools: tuple[str, ...] = ()
    """Tool sources the agent needs, by name (e.g. a toolbox or MCP server)."""
    eval_suite: Path | None = None


def load_spec(path: Path) -> AgentSpec:
    """Load a spec and resolve relative paths against the spec's directory."""
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping")
    raw = cast("dict[str, Any]", loaded)
    base = path.parent
    instructions_file = base / str(raw.pop("instructions"))
    raw["instructions"] = instructions_file.read_text(encoding="utf-8").strip()
    if raw.get("eval_suite"):
        raw["eval_suite"] = (base / str(raw["eval_suite"])).resolve()
    return AgentSpec.model_validate(raw)
