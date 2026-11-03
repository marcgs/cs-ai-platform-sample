"""Publish recorded measurements, never rerun an agent or decide the quality gate."""

import hashlib
import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from openai import APIStatusError, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from csai.eval_receipts import (
    PublicationReceipt,
    ReceiptStore,
    SuiteReceipt,
    legacy_publication_receipt,
    publication_receipt,
    suite_receipt,
)

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.evals.run_create_response import RunCreateResponse
    from openai.types.evals.run_retrieve_response import RunRetrieveResponse

BUILTIN_EVALUATORS = (
    "task_adherence",
    "intent_resolution",
    "coherence",
    "tool_call_accuracy",
)
POLL_INTERVAL_S = 10.0
TIMEOUT_S = 900.0
RECEIPT_DIRECTORY = Path.home() / ".csai" / "publication-measurements"
LEGACY_RECEIPT_DIRECTORY = Path(".eval-results/.publications")
SUITE_DIRECTORY = Path.home() / ".csai" / "publication-suites"


class FoundryEvalError(RuntimeError):
    """Publishing failed; the saved measurement and its gate are unchanged."""


def _confirmed_rejection(error: APIStatusError) -> bool:
    return error.status_code in {400, 401, 403, 404, 422, 429}


def _migrate_receipt(
    receipts: ReceiptStore[PublicationReceipt],
    legacy: ReceiptStore[PublicationReceipt] | None,
    key: str,
) -> None:
    if legacy is None:
        return
    old = legacy.read()
    if old is None:
        return
    current = receipts.read()
    if old.key != key or (
        current is not None
        and (
            current.key != key
            or current.evaluation_id != old.evaluation_id
            or (current.run_id is not None and old.run_id not in {None, current.run_id})
        )
    ):
        raise FoundryEvalError("Legacy publication receipt conflicts with shared submission state.")
    if current is None or (current.run_id is None and old.run_id is not None):
        receipts.write(old)


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
    tool_trace_complete: bool = False
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
    coordination: Literal["shared-v1"] | None = Field(default=None, exclude=True)

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
        specification = {
            "metrics": {_metric_name(name): "increase" for name in self.metric_names},
            "judges": BUILTIN_EVALUATORS,
            "schema": 4,
        }
        return hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()

    @property
    def measurement_id(self) -> str:
        """Hash only frozen observations and provenance, never a path or receipt."""
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def items(self) -> list[dict[str, JsonValue]]:
        """Retain full provenance and scores; do not zero-fill inapplicable metrics."""
        return [{"item": row.model_dump(mode="json")} for row in self.rows]


def mirror_code(metric: str) -> str:
    """Report an applicable score as higher-is-better without filling missing values."""
    value = f"float(item['scores'][{metric!r}])"
    if metric == "calibration":
        value = f"1.0 - {value}"
    return f"def grade(sample: dict, item: dict) -> float:\n    return {value}\n"


def _metric_name(metric: str) -> str:
    return "calibration_score" if metric == "calibration" else metric


def evaluator_definition(metric: str) -> dict[str, Any]:
    """Build the code evaluator's SDK payload; all SDK dictionaries stay at this boundary."""
    return {
        "name": f"csai_{_metric_name(metric)}",
        "evaluator_type": "custom",
        "categories": ["quality"],
        "display_name": f"Recorded {_metric_name(metric)}",
        "description": (
            "calibration_score = 1 - calibration (binary Brier loss). Higher is better; "
            "the recorded local loss and gates are unchanged. "
            if metric == "calibration"
            else "Precomputed csai score. "
        )
        + "Missing scores are inapplicable, not zero.",
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
    """Combine recorded or derived scores with informational model judges."""
    code = [
        {
            "type": "azure_ai_evaluator",
            "name": f"code_{_metric_name(metric)}",
            "evaluator_name": f"csai_{_metric_name(metric)}",
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
                    {"tool_definitions": "{{item.tool_definitions}}"} if name != "coherence" else {}
                ),
                **({"tool_calls": "{{item.tool_calls}}"} if name == "tool_call_accuracy" else {}),
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
    cache: ReceiptStore[SuiteReceipt],
    cache_key: str,
    known_evaluation_id: str | None = None,
) -> str:
    receipt = cache.read()
    if receipt is not None and (
        receipt.key != cache_key
        or receipt.definition_key != publication.definition_key
        or receipt.judge_model != model
    ):
        raise FoundryEvalError(
            "The suite's published evaluator schema differs. Review its version before "
            "publishing; no duplicate evaluation was created."
        )
    matches = [
        evaluation
        for evaluation in client.evals.list()
        if (evaluation.metadata or {}).get("csai_suite") == publication.suite
    ]
    if len(matches) > 1:
        raise FoundryEvalError("Multiple suite evaluations exist; select the canonical one first")
    cached_id = receipt.evaluation_id if receipt is not None else None
    if cached_id is not None and known_evaluation_id not in {None, cached_id}:
        raise FoundryEvalError("Measurement receipt conflicts with the suite evaluation.")
    evaluation_id = cached_id or known_evaluation_id
    if evaluation_id is not None:
        if matches and matches[0].id != evaluation_id:
            raise FoundryEvalError("Suite receipt conflicts with the visible evaluation.")
        evaluation = client.evals.retrieve(evaluation_id)
    elif matches:
        evaluation = matches[0]
    else:
        if receipt is not None:
            raise FoundryEvalError(
                "The prior suite creation outcome is unknown and no evaluation is visible. "
                "No duplicate was created; retry lookup later."
            )
        versions = {
            metric: project.beta.evaluators.create_version(
                name=f"csai_{_metric_name(metric)}", evaluator_version=evaluator_definition(metric)
            ).version
            for metric in publication.metric_names
        }
        cache.write(
            SuiteReceipt(
                key=cache_key, definition_key=publication.definition_key, judge_model=model
            )
        )
        try:
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
        except APIStatusError as error:
            if _confirmed_rejection(error):
                cache.clear()
            raise
    metadata = evaluation.metadata or {}
    if (
        metadata.get("csai_suite") != publication.suite
        or metadata.get("definition_key") != publication.definition_key
        or metadata.get("judge_model") != model
    ):
        raise FoundryEvalError(
            "The suite's published evaluator schema differs. Review its version before "
            "publishing; no duplicate evaluation was created."
        )
    cache.write(
        SuiteReceipt(
            key=cache_key,
            definition_key=publication.definition_key,
            judge_model=model,
            evaluation_id=evaluation.id,
        )
    )
    return evaluation.id


def _publication_name(publication: Publication, retry_of: str | None = None) -> str:
    name = f"{publication.suite}-{publication.metadata['started_at']}"
    return f"{name}-retry-of-{retry_of}" if retry_of is not None else name


def _retry_key(receipt_key: str, retry_of: str) -> str:
    return hashlib.sha256(
        json.dumps([receipt_key, "infrastructure-retry", retry_of]).encode()
    ).hexdigest()


def _recorded_run(
    publication: Publication,
    client: OpenAI,
    evaluation_id: str,
    original: PublicationReceipt,
    receipt_key: str,
    run_id: str,
) -> RunRetrieveResponse:
    """Require positive receipt lineage back to the unchanged original submission."""
    requested = client.evals.runs.retrieve(run_id, eval_id=evaluation_id)
    run = requested
    expected_id = run_id
    visited: set[str] = set()
    prefix = f"{_publication_name(publication)}-retry-of-"
    metadata = {**publication.metadata, "csai_measurement": publication.measurement_id}
    while True:
        if run.id != expected_id or run.id in visited:
            raise FoundryEvalError("Publication retry lineage conflicts or contains a cycle.")
        visited.add(run.id)
        if any((run.metadata or {}).get(key) != value for key, value in metadata.items()):
            raise FoundryEvalError("Retained run evidence conflicts with the frozen measurement.")
        if run.id == original.run_id:
            return requested
        name = getattr(run, "name", None)
        if not isinstance(name, str) or not name.startswith(prefix) or name == prefix:
            raise FoundryEvalError("Publication retry lineage is not recorded.")
        parent_id = name[len(prefix) :]
        key = _retry_key(receipt_key, parent_id)
        receipt = ReceiptStore(RECEIPT_DIRECTORY / f"{key}.json", PublicationReceipt).read()
        if (
            receipt is None
            or receipt.key != key
            or receipt.evaluation_id != evaluation_id
            or receipt.run_id != run.id
        ):
            raise FoundryEvalError("Publication retry lineage lacks matching receipt evidence.")
        expected_id = parent_id
        run = client.evals.runs.retrieve(parent_id, eval_id=evaluation_id)


def _publication_run(
    publication: Publication,
    client: OpenAI,
    evaluation_id: str,
    receipts: ReceiptStore[PublicationReceipt],
    receipt_key: str,
    legacy: ReceiptStore[PublicationReceipt] | None,
    *,
    run_name: str | None = None,
) -> RunCreateResponse | RunRetrieveResponse:
    measurement_id = publication.measurement_id
    metadata = {**publication.metadata, "csai_measurement": measurement_id}
    receipt = receipts.read()
    if receipt is not None and (
        receipt.key != receipt_key or receipt.evaluation_id != evaluation_id
    ):
        raise FoundryEvalError("Publication receipt conflicts with the suite evaluation.")
    matches = [
        run
        for run in client.evals.runs.list(eval_id=evaluation_id)
        if (run.metadata or {}).get("csai_measurement") == measurement_id
        and (run_name is None or getattr(run, "name", None) == run_name)
    ]
    if run_name is None:
        prefix = f"{_publication_name(publication)}-retry-of-"
        for candidate in matches.copy():
            name = getattr(candidate, "name", None)
            if not isinstance(name, str) or not name.startswith(prefix):
                continue
            if receipt is None or receipt.run_id is None:
                raise FoundryEvalError("Original receipt is required to reconcile retry attempts.")
            _recorded_run(publication, client, evaluation_id, receipt, receipt_key, candidate.id)
            matches.remove(candidate)
    if len(matches) > 1:
        raise FoundryEvalError("Duplicate measurement runs exist; no new run was submitted.")
    if run_name is not None and matches and receipt is None:
        raise FoundryEvalError("Publication retry lineage lacks matching receipt evidence.")
    run_id = receipt.run_id if receipt else None
    if run_id is not None and matches and matches[0].id != run_id:
        raise FoundryEvalError("Publication receipt conflicts with the recorded remote run.")
    if run_id is None and matches:
        run_id = matches[0].id
    if run_id is not None:
        run = client.evals.runs.retrieve(run_id, eval_id=evaluation_id)
        if run.id != run_id or any(
            (run.metadata or {}).get(key) != value for key, value in metadata.items()
        ):
            raise FoundryEvalError("Original run evidence conflicts with the frozen measurement.")
        if run_name is not None and getattr(run, "name", None) != run_name:
            raise FoundryEvalError("Publication retry receipt conflicts with its remote run name.")
        receipts.write(
            PublicationReceipt(key=receipt_key, evaluation_id=evaluation_id, run_id=run_id)
        )
        return run
    if receipt is not None:
        raise FoundryEvalError(
            "The prior submission outcome is unknown and no matching run is visible. "
            "No duplicate was submitted; retry lookup later or inspect the remote evaluation."
        )
    receipts.write(PublicationReceipt(key=receipt_key, evaluation_id=evaluation_id))
    try:
        run = client.evals.runs.create(
            eval_id=evaluation_id,
            name=run_name or _publication_name(publication),
            metadata=metadata,
            data_source={
                "type": "jsonl",
                "source": {"type": "file_content", "content": publication.items()},
            },  # pyright: ignore[reportArgumentType]
        )
    except APIStatusError as error:
        if _confirmed_rejection(error):
            # Clear legacy first so a failed shared clear cannot reimport stale pending state.
            if legacy is not None:
                legacy.clear()
            receipts.clear()
        raise
    receipts.write(PublicationReceipt(key=receipt_key, evaluation_id=evaluation_id, run_id=run.id))
    return run


def _retry_publication_run(
    publication: Publication,
    client: OpenAI,
    evaluation_id: str,
    original: PublicationReceipt,
    receipt_key: str,
    retry_of: str,
) -> RunCreateResponse | RunRetrieveResponse:
    previous = _recorded_run(publication, client, evaluation_id, original, receipt_key, retry_of)
    error = previous.error
    code = str(error.code) if error else ""
    message = error.message if error else ""
    startup_error = code == "EvaluationSessionNotBound" or (
        code == "UserError"
        and "(EvaluationSessionNotBound)" in message
        and "Code: EvaluationSessionNotBound" in message.splitlines()
        and "ErrorCode:EvaluationSessionNotBound" in message.splitlines()
    )
    counts = previous.result_counts
    if (
        previous.status != "failed"
        or not startup_error
        or counts.total != 0
        or counts.passed != 0
        or counts.failed != 0
        or counts.errored not in {None, 0}
    ):
        raise FoundryEvalError(
            "Infrastructure retry requires a recorded zero-row EvaluationSessionNotBound failure."
        )
    if list(client.evals.runs.output_items.list(retry_of, eval_id=evaluation_id)):
        raise FoundryEvalError("Infrastructure retry cannot repeat a run with output items.")
    name = _publication_name(publication, retry_of)
    for candidate in client.evals.runs.list(eval_id=evaluation_id):
        if (candidate.metadata or {}).get(
            "csai_measurement"
        ) == publication.measurement_id and getattr(candidate, "name", None) != name:
            _recorded_run(publication, client, evaluation_id, original, receipt_key, candidate.id)
    key = _retry_key(receipt_key, retry_of)
    with publication_receipt(RECEIPT_DIRECTORY, key) as attempt:
        return _publication_run(
            publication, client, evaluation_id, attempt, key, None, run_name=name
        )


def publish(
    publication: Publication,
    *,
    endpoint: str,
    model: str,
    legacy_directory: Path | None = None,
    retry_infrastructure: str | None = None,
) -> str:
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
    if any(
        not row.tool_trace_complete or any(call.get("result_truncated") for call in row.tool_calls)
        for row in publication.rows
    ):
        raise FoundryEvalError(
            "Tool evidence is incomplete or truncated; tool-call accuracy cannot judge this record."
        )
    receipt_key = hashlib.sha256(
        json.dumps([publication.measurement_id, endpoint, model]).encode()
    ).hexdigest()
    suite_key = hashlib.sha256(json.dumps([endpoint, publication.suite]).encode()).hexdigest()
    if legacy_directory is not None and (
        not legacy_directory.is_dir() or not (legacy_directory / f"{receipt_key}.json").is_file()
    ):
        raise FoundryEvalError(
            "Original legacy receipt evidence is unavailable; no submission. "
            "--legacy-receipts requires a matching receipt, not an assertion of non-submission."
        )
    try:
        with (
            publication_receipt(RECEIPT_DIRECTORY, receipt_key) as receipts,
            legacy_publication_receipt(
                legacy_directory if legacy_directory is not None else LEGACY_RECEIPT_DIRECTORY,
                receipt_key,
                allow_absent=legacy_directory is None,
            ) as legacy,
        ):
            _migrate_receipt(receipts, legacy, receipt_key)
            prior = receipts.read()
            if retry_infrastructure is not None and (
                not retry_infrastructure.strip()
                or prior is None
                or prior.key != receipt_key
                or prior.run_id is None
            ):
                raise FoundryEvalError(
                    "Infrastructure retry requires the retained original submitted-run receipt."
                )
            if publication.coordination is None and prior is None:
                raise FoundryEvalError(
                    "Legacy publication origin is unknown; no submission was made. "
                    "Supply original receipt evidence with --legacy-receipts, or reconcile "
                    "the legacy publication explicitly. Missing receipts or empty remote listings "
                    "do not prove non-submission, even for a never-published legacy archive."
                )
            with (
                DefaultAzureCredential() as credential,
                AIProjectClient(endpoint, credential) as project,
                project.get_openai_client(max_retries=0) as client,
            ):
                with suite_receipt(SUITE_DIRECTORY, suite_key) as cache:
                    evaluation_id = _evaluation(
                        publication,
                        project,
                        client,
                        model,
                        cache,
                        suite_key,
                        prior.evaluation_id if prior else None,
                    )
                if retry_infrastructure is not None:
                    if prior is None or prior.evaluation_id != evaluation_id:
                        raise FoundryEvalError("Original receipt conflicts with the evaluation.")
                    run = _retry_publication_run(
                        publication,
                        client,
                        evaluation_id,
                        prior,
                        receipt_key,
                        retry_infrastructure,
                    )
                else:
                    run = _publication_run(
                        publication, client, evaluation_id, receipts, receipt_key, legacy
                    )
                deadline = time.monotonic() + TIMEOUT_S
                while run.status in {"queued", "in_progress"} and time.monotonic() < deadline:
                    time.sleep(POLL_INTERVAL_S)
                    run = client.evals.runs.retrieve(run.id, eval_id=evaluation_id)
                if run.status != "completed" or run.result_counts.errored:
                    reason = (
                        run.error.message if run.error else "timed out or item evaluator errors"
                    )
                    raise FoundryEvalError(
                        f"Foundry evaluation {run.status}: {reason}. "
                        "Sparse metrics remain inapplicable; inspect per-item evaluator errors."
                    )
                return run.report_url or run.id
    except (AzureError, OpenAIError, OSError) as error:
        raise FoundryEvalError(f"Foundry publication failed: {error}") from error
