"""Publish recorded measurements, never rerun an agent or decide the quality gate."""

import hashlib
import json
import math
import time
from typing import TYPE_CHECKING, Any

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, JsonValue

if TYPE_CHECKING:
    from openai import OpenAI

BUILTIN_EVALUATORS = (
    "task_adherence",
    "intent_resolution",
    "coherence",
    "tool_call_accuracy",
)
POLL_INTERVAL_S = 10.0
TIMEOUT_S = 900.0


class FoundryEvalError(RuntimeError):
    """Publishing failed; the saved measurement and its gate are unchanged."""


class PublishedRow(BaseModel):
    """The immutable observation sent to Foundry, including applicability."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    repeat: int
    split: str
    category: str
    cohort: str
    query: str
    response: str
    ground_truth: dict[str, JsonValue]
    tool_calls: list[dict[str, JsonValue]]
    tool_definitions: list[dict[str, JsonValue]]
    scores: dict[str, float]
    gated: bool
    failure: JsonValue = None
    source: str = "synthetic"


class Publication(BaseModel):
    """A disk-derived publication, with the run's original version identities."""

    model_config = ConfigDict(extra="forbid")

    suite: str
    metadata: dict[str, str]
    rows: list[PublishedRow]

    @property
    def metric_names(self) -> tuple[str, ...]:
        if not self.rows or any(
            isinstance(row.failure, dict) and row.failure.get("kind") == "plumbing"
            for row in self.rows
        ):
            return ()
        common = set(self.rows[0].scores)
        for row in self.rows[1:]:
            common.intersection_update(row.scores)
        return tuple(sorted(common))

    @property
    def definition_key(self) -> str:
        specification = {"metrics": self.metric_names, "judges": BUILTIN_EVALUATORS, "schema": 1}
        return hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()

    def items(self) -> list[dict[str, JsonValue]]:
        """Retain full provenance and scores; do not zero-fill inapplicable metrics."""
        return [{"item": row.model_dump(mode="json")} for row in self.rows]


def mirror_code(metric: str) -> str:
    """Mirror an applicable recorded score without inventing a missing score."""
    return (
        "def grade(sample: dict, item: dict) -> float:\n"
        f"    return float(item['scores'][{metric!r}])\n"
    )


def evaluator_definition(metric: str) -> dict[str, Any]:
    """Build the code evaluator's SDK payload; all SDK dictionaries stay at this boundary."""
    return {
        "name": f"csai_{metric}",
        "evaluator_type": "custom",
        "categories": ["quality"],
        "display_name": f"Recorded {metric}",
        "description": "Precomputed csai score. Missing scores are inapplicable, not zero.",
        "definition": {
            "type": "code",
            "code_text": mirror_code(metric),
            "init_parameters": {
                "type": "object",
                "properties": {
                    "deployment_name": {"type": "string"},
                    "pass_threshold": {"type": "number"},
                },
                "required": ["deployment_name", "pass_threshold"],
            },
            "data_schema": {
                "type": "object",
                "properties": {"scores": {"type": "object"}},
                "required": ["scores"],
            },
            "metrics": {
                "result": {
                    "type": "continuous",
                    "desirable_direction": "increase",
                    "min_value": 0.0,
                    "max_value": 1.0,
                }
            },
        },
    }


def testing_criteria(
    metrics: tuple[str, ...], versions: dict[str, str], model: str
) -> list[dict[str, Any]]:
    """Combine exact recorded scores with informational model judges."""
    code = [
        {
            "type": "azure_ai_evaluator",
            "name": f"code_{metric}",
            "evaluator_name": f"csai_{metric}",
            "evaluator_version": versions[metric],
            "initialization_parameters": {"deployment_name": model, "pass_threshold": 0.5},
            "data_mapping": {"scores": "{{item.scores}}"},
        }
        for metric in metrics
    ]
    judges = [
        {
            "type": "azure_ai_evaluator",
            "name": name,
            "evaluator_name": f"builtin.{name}",
            "initialization_parameters": {"deployment_name": model},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                **(
                    {
                        "tool_calls": "{{item.tool_calls}}",
                        "tool_definitions": "{{item.tool_definitions}}",
                    }
                    if name == "tool_call_accuracy"
                    else {}
                ),
            },
        }
        for name in BUILTIN_EVALUATORS
    ]
    return code + judges


def _evaluation(
    publication: Publication,
    project: AIProjectClient,
    client: OpenAI,
    model: str,
) -> str:
    matches = [
        evaluation
        for evaluation in client.evals.list()
        if (evaluation.metadata or {}).get("csai_suite") == publication.suite
    ]
    if len(matches) > 1:
        raise FoundryEvalError("Multiple suite evaluations exist; select the canonical one first")
    if matches:
        evaluation = matches[0]
        metadata = evaluation.metadata or {}
        if (
            metadata.get("definition_key") != publication.definition_key
            or metadata.get("judge_model") != model
        ):
            raise FoundryEvalError(
                "The suite's published evaluator schema differs. Review its version before "
                "publishing; no duplicate evaluation was created."
            )
        return evaluation.id
    versions = {
        metric: project.beta.evaluators.create_version(
            name=f"csai_{metric}", evaluator_version=evaluator_definition(metric)
        ).version
        for metric in publication.metric_names
    }
    evaluation = client.evals.create(
        name=f"{publication.suite} agent",
        metadata={
            "csai_suite": publication.suite,
            "definition_key": publication.definition_key,
            "judge_model": model,
        },
        data_source_config={
            "type": "custom",
            "item_schema": PublishedRow.model_json_schema(),
            "include_sample_schema": False,
        },
        testing_criteria=testing_criteria(publication.metric_names, versions, model),  # pyright: ignore[reportArgumentType]
    )
    return evaluation.id


def publish(publication: Publication, *, endpoint: str, model: str) -> str:
    """Publish a saved run, returning its report URL; never mutate the local record."""
    if not publication.rows:
        raise FoundryEvalError("The record has no completed case-runs to publish")
    if any(
        not math.isfinite(score) or not 0 <= score <= 1
        for row in publication.rows
        for score in row.scores.values()
    ):
        raise FoundryEvalError("A recorded score is outside the code evaluator's [0, 1] range")
    if any(not row.tool_definitions for row in publication.rows if row.tool_calls):
        raise FoundryEvalError(
            "Tool definitions were not captured for this run; tool-call judging cannot be "
            "reconstructed from today's tools"
        )
    try:
        with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint, credential) as project,
            project.get_openai_client() as client,
        ):
            evaluation_id = _evaluation(publication, project, client, model)
            run = client.evals.runs.create(
                eval_id=evaluation_id,
                name=f"{publication.suite}-{publication.metadata['started_at']}",
                metadata=publication.metadata,
                data_source={
                    "type": "jsonl",
                    "source": {"type": "file_content", "content": publication.items()},
                },  # pyright: ignore[reportArgumentType]
            )
            deadline = time.monotonic() + TIMEOUT_S
            while run.status in {"queued", "in_progress"} and time.monotonic() < deadline:
                time.sleep(POLL_INTERVAL_S)
                run = client.evals.runs.retrieve(run.id, eval_id=evaluation_id)
            if run.status != "completed" or run.result_counts.errored:
                reason = run.error.message if run.error else "timed out or item evaluator errors"
                raise FoundryEvalError(
                    f"Foundry evaluation {run.status}: {reason}. "
                    "Sparse metrics remain inapplicable; inspect per-item evaluator errors."
                )
            return run.report_url or run.id
    except (AzureError, OpenAIError, OSError) as error:
        raise FoundryEvalError(f"Foundry publication failed: {error}") from error
