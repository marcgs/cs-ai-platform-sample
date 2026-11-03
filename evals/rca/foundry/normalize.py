"""Prepare a private second-pass dataset from retained Foundry outputs."""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, JsonValue

CALL_TYPES = {"function_call", "tool_call", "mcp_call"}


class RetainedItem(BaseModel):
    """Keep the original generated fields rather than invoking the agent again."""

    datasource_item: dict[str, JsonValue]


def normalize_arguments(text: str) -> dict[str, JsonValue]:
    """Decode arguments, collapsing repeated complete objects only when identical."""

    def unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate tool argument key")
            result[key] = value
        return result

    decoder = json.JSONDecoder(object_pairs_hook=unique_object)
    remaining = text.strip()
    objects: list[dict[str, JsonValue]] = []
    while remaining:
        value, end = decoder.raw_decode(remaining)
        if not isinstance(value, dict):
            raise ValueError("Tool arguments are not an object")
        objects.append(value)
        remaining = remaining[end:].strip()
    if not objects or any(
        json.dumps(value, sort_keys=True) != json.dumps(objects[0], sort_keys=True)
        for value in objects
    ):
        raise ValueError("Missing or conflicting tool argument objects")
    return objects[0]


def normalize(value: JsonValue) -> JsonValue:
    """Change argument representation only; preserve messages and tool results."""
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") in ("function_result", "tool_result", "function_call_output"):
        return value
    result = {key: normalize(item) for key, item in value.items()}
    kind = result.get("type")
    if isinstance(kind, str) and kind in CALL_TYPES and isinstance(result.get("arguments"), str):
        result["arguments"] = normalize_arguments(str(result["arguments"]))
    return result


def main() -> None:
    """Write all normalized rows only after every source row validates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Private JSONL, never tracked")
    args = parser.parse_args()
    rows = [RetainedItem.model_validate(row) for row in json.loads(args.source.read_text())]
    records: list[dict[str, JsonValue]] = []
    for row in rows:
        item = row.datasource_item
        source = item.get("item", item)
        if not isinstance(source, dict):
            raise ValueError("Missing source dataset item")
        if not isinstance(item.get("sample.output_text"), str):
            raise ValueError("Missing retained report text")
        if not isinstance(item.get("sample.output_items"), list):
            raise ValueError("Missing retained output items")
        records.append(
            {
                "case_id": source["case_id"],
                "query": source["query"],
                "expected": source["expected"],
                "truth": source["truth"],
                "response": item["sample.output_text"],
                "output_items": normalize(item["sample.output_items"]),
                "tool_definitions": source["tool_definitions"],
                "source_response_id": item["response_id"],
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records))
    print(f"Normalized {len(records)} retained outputs; no agent calls")


if __name__ == "__main__":
    main()
