from typing import Any

from rca_agent.report import RcaReport


def _objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Every object definition in a JSON schema, including $defs."""
    found: list[dict[str, Any]] = []
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            typed: dict[str, Any] = node  # pyright: ignore[reportUnknownVariableType]
            if typed.get("type") == "object" and "properties" in typed:
                found.append(typed)
            stack.extend(typed.values())
        elif isinstance(node, list):
            stack.extend(node)  # pyright: ignore[reportUnknownArgumentType]
    return found


def test_schema_is_compatible_with_strict_structured_outputs() -> None:
    objects = _objects(RcaReport.model_json_schema())
    assert len(objects) == 3  # report, hypothesis, evidence
    for obj in objects:
        assert obj.get("additionalProperties") is False, obj.get("title")
        assert set(obj["required"]) == set(obj["properties"]), obj.get("title")


def test_every_field_is_described_for_the_model() -> None:
    hypothesis = RcaReport.model_json_schema()["$defs"]["Hypothesis"]["properties"]
    assert all("description" in prop for prop in hypothesis.values())
