"""Adapt immutable on-disk measurements to Foundry's reporting boundary."""

from typing import TYPE_CHECKING

from cs_platform.eval_runs import read_run
from cs_platform.evals import is_plumbing
from cs_platform.settings import PlatformSettings
from csai.foundry import Publication, PublishedRow, publish

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue


def _definitions(definitions: list[dict[str, JsonValue]] | None) -> list[dict[str, JsonValue]]:
    result: list[dict[str, JsonValue]] = []
    for definition in definitions or []:
        function = definition.get("function")
        result.append(
            {"type": "function", **function} if isinstance(function, dict) else definition
        )
    return result


def publication_from_record(path: Path) -> Publication:
    """Read frozen cases, observations and identities without calling targets or evaluators."""
    record = read_run(path)
    manifest = record.manifest
    metadata = manifest.metadata
    cases = {case.id: case for case in manifest.cases}
    rows: list[PublishedRow] = []
    for result in record.result.cases:
        case = cases[result.case_id]
        rows.append(
            PublishedRow.model_validate(
                {
                    "case_id": case.id,
                    "repeat": result.repeat,
                    "split": case.split or result.split or "unknown",
                    "category": result.category,
                    "cohort": manifest.cohorts[case.id],
                    "query": case.input,
                    "response": result.output.text or result.output.error or "",
                    "ground_truth": {
                        "expected": case.expected,
                        "truth": case.truth.model_dump(mode="json") if case.truth else None,
                        "provenance": case.model_dump(mode="json").get("provenance"),
                    },
                    "tool_calls": [
                        {
                            "type": "tool_call",
                            "tool_call_id": f"{case.id}:{result.repeat}:{index}",
                            "name": call.name,
                            "arguments": call.arguments,
                            "result": call.result,
                            "result_truncated": call.result_truncated,
                            "error": call.error,
                        }
                        for index, call in enumerate(result.output.tool_trace)
                    ],
                    "tool_trace_complete": result.output.tool_trace_complete,
                    "tool_definitions": _definitions(
                        result.output.tool_definitions
                        if result.output.tool_definitions is not None
                        else metadata.tool_definitions
                    ),
                    "scores": result.scores,
                    "gated": result.gated,
                    "failure": (
                        result.output.failure.model_dump(mode="json")
                        if result.output.failure
                        else None
                    ),
                    "source": metadata.source,
                }
            )
        )
    publication = Publication(
        coordination=(
            manifest.publication_coordination
            if manifest.completion_protocol == "certificate-v1" and record.status == "complete"
            else None
        ),
        suite=manifest.suite,
        metadata={
            "revision": metadata.agent_revision,
            "harness_revision": metadata.harness_revision,
            "harness_dirty": str(metadata.harness_dirty).lower(),
            "agent_version": metadata.agent_version or "unknown",
            "skill_version": metadata.skill_version or "unknown",
            "dataset_version": metadata.dataset_version or "unknown",
            "split": ",".join(sorted({row.split for row in rows})) or "unknown",
            "cohort": ",".join(sorted({row.cohort for row in rows})) or "unknown",
            "source": metadata.source,
            "target": metadata.target,
            "started_at": metadata.started_at.isoformat(),
            "repeats": str(metadata.repeats),
            "model": metadata.model,
            "status": record.status,
        },
        rows=rows,
    )
    all_metrics = {name for row in rows for name in row.scores}
    publication.metadata["metric_parity"] = (
        "blocked:sparse_or_plumbing"
        if all_metrics - set(publication.metric_names)
        or any(
            is_plumbing(result.output, error_policy=record.result.error_policy)
            for result in record.result.cases
        )
        else "unverified"
    )
    return publication


def publish_record(
    path: Path,
    *,
    legacy_receipts: Path | None = None,
    retry_infrastructure: str | None = None,
) -> str:
    """Publish exactly one saved measurement; configuration supplies only endpoint and judge."""
    publication = publication_from_record(path)
    settings = PlatformSettings.from_env()
    if retry_infrastructure is not None:
        return publish(
            publication,
            endpoint=settings.foundry_project_endpoint,
            model=settings.model_deployment,
            legacy_directory=legacy_receipts,
            retry_infrastructure=retry_infrastructure,
        )
    if legacy_receipts is not None:
        return publish(
            publication,
            endpoint=settings.foundry_project_endpoint,
            model=settings.model_deployment,
            legacy_directory=legacy_receipts,
        )
    return publish(
        publication, endpoint=settings.foundry_project_endpoint, model=settings.model_deployment
    )
