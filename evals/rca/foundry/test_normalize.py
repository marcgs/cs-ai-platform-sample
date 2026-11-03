"""Normalization must not invent or choose conflicting tool arguments."""

from typing import TYPE_CHECKING

import pytest

from .normalize import normalize, normalize_arguments

if TYPE_CHECKING:
    from pydantic import JsonValue


def test_identical_repeated_argument_objects_collapse() -> None:
    assert normalize_arguments('{"machine_id":"M-0001"} {"machine_id":"M-0001"}') == {
        "machine_id": "M-0001"
    }


@pytest.mark.parametrize(
    "text", ['{"x":1}{"x":2}', '{"x":true}{"x":1}', '{"x":1,"x":2}', "", "[]", '{"x":']
)
def test_conflicting_or_malformed_arguments_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match=r"argument|Expecting"):
        normalize_arguments(text)


def test_other_output_content_is_preserved() -> None:
    items: list[JsonValue] = [
        {"content": [{"type": "function_call", "name": "tool", "arguments": '{"x":1}'}]},
        {"content": [{"type": "function_result", "result": '{"x":1}{"x":2}'}]},
        {"type": "function_result", "result": {"type": "function_call", "arguments": '{"x":1}'}},
    ]
    assert normalize(items) == [
        {"content": [{"type": "function_call", "name": "tool", "arguments": {"x": 1}}]},
        items[1],
        items[2],
    ]
