"""Foundry is faked at the SDK boundary; these tests never authenticate or call a model."""

import hashlib
import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest
from httpx2 import Request, Response
from openai import APIStatusError

from csai import eval_receipts, foundry


@pytest.fixture(autouse=True)
def private_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry, "RECEIPT_DIRECTORY", tmp_path / "receipts")
    monkeypatch.setattr(foundry, "LEGACY_RECEIPT_DIRECTORY", tmp_path / "legacy")
    monkeypatch.setattr(foundry, "SUITE_DIRECTORY", tmp_path / "user-state" / "suites")


def publication(
    *, observations_digest="frozen-observations", tool_calls=None, tool_definitions=None
):
    return foundry.Publication(
        coordination="shared-v1",
        suite="rca",
        observations_digest=observations_digest,
        metadata={
            "started_at": "2026-10-30T12:00:00+00:00",
            "revision": "revision",
            "agent_version": "1",
            "skill_version": "1",
            "dataset_version": "digest",
            "source": "synthetic",
        },
        rows=[
            foundry.PublishedRow(
                case_id="case-1",
                repeat=1,
                split="train",
                category="clean",
                cohort="regression",
                query="M-0001: synthetic incident",
                response="synthetic answer",
                ground_truth={"failure_mode_id": "FM-01"},
                tool_calls=tool_calls or [],
                tool_trace_complete=True,
                tool_definitions=tool_definitions or [],
                gated=True,
            )
        ],
    )


def existing_suite(recorded):
    return SimpleNamespace(
        id="eval-id",
        metadata={
            "csai_suite": recorded.suite,
            "definition_key": recorded.definition_key,
            "judge_model": "judge",
        },
    )


def fake_boundary(
    monkeypatch,
    *,
    status="completed",
    errored=0,
    existing=None,
    run_state=None,
    create_error=None,
    list_hook=None,
    create_hook=None,
    evaluation_error=None,
    run_hook=None,
    run_list_hook=None,
    output_items=None,
):
    calls = []
    evaluations = list(existing or [])
    runs = [] if run_state is None else run_state

    def next_error(error):
        return (error.pop(0) if error else None) if isinstance(error, list) else error

    def create_evaluation(**kwargs):
        if create_hook:
            create_hook()
        calls.append(("evaluation", kwargs))
        error = next_error(evaluation_error)
        if isinstance(error, APIStatusError):
            raise error
        evaluation = SimpleNamespace(
            id="eval-id" if not evaluations else f"eval-id-{len(evaluations) + 1}",
            metadata=kwargs["metadata"],
        )
        evaluations.append(evaluation)
        if error is not None:
            raise error
        return evaluation

    def create_run(**kwargs):
        calls.append(("run", kwargs))
        error = next_error(create_error)
        if isinstance(error, APIStatusError):
            raise error
        if run_hook is not None:
            run_hook()
        run = SimpleNamespace(
            id="run-id" if not runs else f"run-id-{len(runs) + 1}",
            name=kwargs["name"],
            metadata=kwargs["metadata"],
            status=next_error(status),
            result_counts=SimpleNamespace(errored=errored),
            error=None,
            report_url="https://example.test/report",
        )
        runs.append(run)
        if error is not None:
            raise error
        return run

    def retrieve(run_id, **kwargs):
        calls.append(("retrieve", kwargs))
        return next(run for run in runs if run.id == run_id)

    client = SimpleNamespace(
        evals=SimpleNamespace(
            list=lambda: list_hook(evaluations) if list_hook else evaluations,
            retrieve=lambda evaluation_id: next(
                evaluation for evaluation in evaluations if evaluation.id == evaluation_id
            ),
            create=create_evaluation,
            runs=SimpleNamespace(
                create=create_run,
                list=lambda **_: run_list_hook(runs) if run_list_hook else runs,
                retrieve=retrieve,
                output_items=SimpleNamespace(list=lambda *args, **kwargs: output_items or []),
            ),
        )
    )
    project = SimpleNamespace(
        get_openai_client=lambda **options: (
            nullcontext(client)
            if options == {"max_retries": 0}
            else pytest.fail(f"Unexpected client options: {options}")
        ),
    )
    monkeypatch.setattr(foundry, "DefaultAzureCredential", lambda: nullcontext(object()))
    monkeypatch.setattr(foundry, "AIProjectClient", lambda *args: nullcontext(project))
    return calls


def startup_failure(monkeypatch, **options):
    runs = []
    options.setdefault("status", ["failed", "completed"])
    calls = fake_boundary(monkeypatch, run_state=runs, **options)
    recorded = publication()
    with pytest.raises(foundry.FoundryEvalError, match="evaluation failed"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    runs[0].result_counts = SimpleNamespace(total=0, passed=0, failed=0, errored=None)
    runs[0].error = SimpleNamespace(
        code="UserError",
        message="Azure Storage resource already exists: (EvaluationSessionNotBound) "
        "The evaluation session is starting. Retry the relay request.\n"
        "Code: EvaluationSessionNotBound\nErrorCode:EvaluationSessionNotBound",
    )
    return recorded, runs, calls


def test_explicit_startup_retry_retains_failure_and_resumes_across_copies(monkeypatch, tmp_path):
    recorded, runs, calls = startup_failure(monkeypatch)
    before = recorded.model_dump_json()
    original_path = next(foundry.RECEIPT_DIRECTORY.glob("*.json"))
    original = original_path.read_bytes()
    previous = runs[0].id
    assert foundry.publish(
        recorded, endpoint="unused", model="judge", retry_infrastructure=previous
    ).endswith("/report")
    copy = tmp_path / "another-worktree"
    copy.mkdir()
    monkeypatch.chdir(copy)
    assert foundry.publish(
        recorded.model_copy(deep=True),
        endpoint="unused",
        model="judge",
        retry_infrastructure=previous,
    ).endswith("/report")
    assert len(runs) == 2
    assert runs[0].status == "failed"
    assert runs[1].name.endswith(f"-retry-of-{previous}")
    assert runs[1].metadata == runs[0].metadata
    assert original_path.read_bytes() == original
    assert recorded.model_dump_json() == before
    assert sum(name == "run" for name, _ in calls) == 2
    with pytest.raises(foundry.FoundryEvalError, match="evaluation failed"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    assert sum(name == "run" for name, _ in calls) == 2


@pytest.mark.parametrize(
    "invalid", ["completed", "other_error", "rows", "errored", "metadata", "items"]
)
def test_startup_retry_rejects_quality_partial_or_conflicting_evidence(monkeypatch, invalid):
    items = [SimpleNamespace(id="partial")] if invalid == "items" else []
    recorded, runs, calls = startup_failure(monkeypatch, output_items=items)
    previous = runs[0]
    if invalid == "completed":
        previous.status = "completed"
    elif invalid == "other_error":
        previous.error.code = "EvaluatorError"
    elif invalid == "rows":
        previous.result_counts.total = 1
    elif invalid == "errored":
        previous.result_counts.errored = 1
    elif invalid == "metadata":
        previous.metadata["revision"] = "different-revision"
    with pytest.raises(foundry.FoundryEvalError):
        foundry.publish(
            recorded, endpoint="unused", model="judge", retry_infrastructure=previous.id
        )
    assert sum(name == "run" for name, _ in calls) == 1


@pytest.mark.parametrize("pending", [False, True])
def test_startup_retry_requires_positive_original_receipt_before_authentication(
    monkeypatch, pending
):
    recorded, _, calls = startup_failure(monkeypatch)
    path = next(foundry.RECEIPT_DIRECTORY.glob("*.json"))
    store = eval_receipts.ReceiptStore(path, eval_receipts.PublicationReceipt)
    original = store.read()
    assert original is not None
    if pending:
        store.write(original.model_copy(update={"run_id": None}))
    else:
        store.clear()
    monkeypatch.setattr(
        foundry,
        "DefaultAzureCredential",
        lambda: pytest.fail("Missing submission evidence must stop before authentication."),
    )
    with pytest.raises(foundry.FoundryEvalError, match="original submitted-run receipt"):
        foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure="run-id")
    assert sum(name == "run" for name, _ in calls) == 1


@pytest.mark.parametrize("visible", [False, True])
def test_uncertain_startup_retry_never_submits_another_attempt(monkeypatch, visible):
    error = (
        RuntimeError("response lost")
        if visible
        else APIStatusError(
            "ambiguous server failure",
            response=Response(500, request=Request("POST", "/evals")),
            body=None,
        )
    )
    recorded, runs, calls = startup_failure(monkeypatch, create_error=[None, error])
    original = next(foundry.RECEIPT_DIRECTORY.glob("*.json")).read_bytes()
    previous = runs[0].id
    with pytest.raises((foundry.FoundryEvalError, RuntimeError)):
        foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure=previous)
    if visible:
        assert foundry.publish(
            recorded, endpoint="unused", model="judge", retry_infrastructure=previous
        ).endswith("/report")
    else:
        with pytest.raises(foundry.FoundryEvalError, match="outcome is unknown"):
            foundry.publish(
                recorded, endpoint="unused", model="judge", retry_infrastructure=previous
            )
    assert sum(name == "run" for name, _ in calls) == 2
    assert original in [p.read_bytes() for p in foundry.RECEIPT_DIRECTORY.glob("*.json")]


def test_explicit_retry_cannot_reconstruct_a_missing_child_receipt(monkeypatch):
    recorded, runs, calls = startup_failure(monkeypatch)
    original_path = next(foundry.RECEIPT_DIRECTORY.glob("*.json"))
    original = original_path.read_bytes()
    previous = runs[0].id
    foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure=previous)
    child_path = next(
        path for path in foundry.RECEIPT_DIRECTORY.glob("*.json") if path != original_path
    )
    eval_receipts.ReceiptStore(child_path, eval_receipts.PublicationReceipt).clear()

    with pytest.raises(foundry.FoundryEvalError, match="matching receipt evidence"):
        foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure=previous)

    assert not child_path.exists()
    assert original_path.read_bytes() == original
    assert sum(name == "run" for name, _ in calls) == 2


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_retry_reconciliation_checks_all_provenance_before_writing_receipts(
    monkeypatch, pending, missing
):
    recorded, runs, calls = startup_failure(monkeypatch)
    original_path = next(foundry.RECEIPT_DIRECTORY.glob("*.json"))
    original = original_path.read_bytes()
    previous = runs[0].id
    foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure=previous)
    child_path = next(
        path for path in foundry.RECEIPT_DIRECTORY.glob("*.json") if path != original_path
    )
    store = eval_receipts.ReceiptStore(child_path, eval_receipts.PublicationReceipt)
    child = store.read()
    assert child is not None
    if pending:
        store.write(child.model_copy(update={"run_id": None}))
    before = child_path.read_bytes()

    for field, value in recorded.metadata.items():
        if missing:
            runs[1].metadata.pop(field)
        else:
            runs[1].metadata[field] = f"conflicting-{value}"
        with pytest.raises(foundry.FoundryEvalError, match="frozen measurement"):
            foundry.publish(
                recorded, endpoint="unused", model="judge", retry_infrastructure=previous
            )
        assert child_path.read_bytes() == before
        assert original_path.read_bytes() == original
        runs[1].metadata[field] = value

    assert sum(name == "run" for name, _ in calls) == 2


def test_queued_startup_retry_resumes_only_its_recorded_run(monkeypatch):
    recorded, runs, calls = startup_failure(monkeypatch, status=["failed", "queued"])
    monkeypatch.setattr(foundry, "TIMEOUT_S", 0)
    previous = runs[0].id
    with pytest.raises(foundry.FoundryEvalPending, match="still running"):
        foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure=previous)
    runs[1].status = "completed"
    assert foundry.publish(
        recorded, endpoint="unused", model="judge", retry_infrastructure=previous
    ).endswith("/report")
    assert sum(name == "run" for name, _ in calls) == 2


def test_concurrent_retry_copies_share_original_measurement_lock(monkeypatch):
    creating = threading.Event()
    release = threading.Event()
    root_created = False

    def hold_retry():
        nonlocal root_created
        if not root_created:
            root_created = True
            return
        creating.set()
        assert release.wait(5)

    recorded, runs, calls = startup_failure(monkeypatch, run_hook=hold_retry)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            foundry.publish,
            recorded,
            endpoint="unused",
            model="judge",
            retry_infrastructure=runs[0].id,
        )
        try:
            assert creating.wait(5)
            with pytest.raises(foundry.FoundryEvalError, match="publication failed"):
                foundry.publish(
                    recorded.model_copy(deep=True),
                    endpoint="unused",
                    model="judge",
                    retry_infrastructure=runs[0].id,
                )
        finally:
            release.set()
        assert first.result(timeout=5).endswith("/report")
    assert sum(name == "run" for name, _ in calls) == 2


def test_recorded_startup_retry_chain_retains_each_failed_attempt(monkeypatch):
    recorded, runs, calls = startup_failure(monkeypatch, status=["failed", "failed", "completed"])
    with pytest.raises(foundry.FoundryEvalError, match="evaluation failed"):
        foundry.publish(recorded, endpoint="unused", model="judge", retry_infrastructure=runs[0].id)
    runs[1].error = runs[0].error
    runs[1].result_counts = SimpleNamespace(total=0, passed=0, failed=0, errored=0)
    assert foundry.publish(
        recorded, endpoint="unused", model="judge", retry_infrastructure=runs[1].id
    ).endswith("/report")
    assert [run.status for run in runs] == ["failed", "failed", "completed"]
    assert sum(name == "run" for name, _ in calls) == 3


def test_unregistered_retry_run_cannot_hide_a_duplicate_measurement(monkeypatch):
    recorded, runs, calls = startup_failure(monkeypatch)
    runs.append(
        SimpleNamespace(
            id="unregistered",
            name=foundry._publication_name(recorded, runs[0].id),
            metadata=runs[0].metadata,
        )
    )
    with pytest.raises(foundry.FoundryEvalError, match="matching receipt evidence"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    assert sum(name == "run" for name, _ in calls) == 1


def test_copied_measurement_reuses_receipt_across_working_directories(monkeypatch, tmp_path):
    calls = fake_boundary(monkeypatch, run_list_hook=lambda _: [])
    recorded = publication()
    first = tmp_path / "first-worktree"
    second = tmp_path / "second-worktree"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    foundry.publish(recorded, endpoint="unused", model="judge")
    monkeypatch.chdir(second)
    foundry.publish(recorded.model_copy(deep=True), endpoint="unused", model="judge")
    assert sum(name == "run" for name, _ in calls) == 1


def test_concurrent_copies_share_measurement_submission_lock(monkeypatch):
    creating = threading.Event()
    release = threading.Event()

    def hold():
        creating.set()
        assert release.wait(5)

    calls = fake_boundary(monkeypatch, run_hook=hold, run_list_hook=lambda _: [])
    recorded = publication()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(foundry.publish, recorded, endpoint="unused", model="judge")
        try:
            assert creating.wait(5)
            with pytest.raises(foundry.FoundryEvalError, match="publication failed"):
                executor.submit(
                    foundry.publish,
                    recorded.model_copy(deep=True),
                    endpoint="unused",
                    model="judge",
                ).result(timeout=2)
        finally:
            release.set()
        assert first.result(timeout=5).endswith("/report")
    assert sum(name == "run" for name, _ in calls) == 1


def test_legacy_pending_migrates_and_blocks_copied_measurement_retry(monkeypatch, tmp_path):
    recorded = publication()
    key = hashlib.sha256(
        json.dumps([recorded.measurement_id, "unused", "judge", recorded.definition_key]).encode()
    ).hexdigest()
    with eval_receipts.publication_receipt(foundry.LEGACY_RECEIPT_DIRECTORY, key) as legacy:
        legacy.write(eval_receipts.PublicationReceipt(key=key, evaluation_id="eval-id"))
        original = legacy.path.read_bytes()
    calls = fake_boundary(monkeypatch, existing=[existing_suite(recorded)])
    with pytest.raises(foundry.FoundryEvalError, match="outcome is unknown"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    assert (foundry.LEGACY_RECEIPT_DIRECTORY / f"{key}.json").read_bytes() == original
    assert (foundry.RECEIPT_DIRECTORY / f"{key}.json").read_bytes() == original
    other = tmp_path / "copied-worktree"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(foundry, "LEGACY_RECEIPT_DIRECTORY", other / "legacy")
    with pytest.raises(foundry.FoundryEvalError, match="outcome is unknown"):
        foundry.publish(recorded.model_copy(deep=True), endpoint="unused", model="judge")
    assert not any(name == "run" for name, _ in calls)


def test_first_copied_legacy_invocation_cannot_ignore_unseen_pending(monkeypatch, tmp_path):
    modern = publication()
    recorded = modern.model_copy(update={"coordination": None}, deep=True)
    assert recorded.measurement_id == modern.measurement_id
    key = hashlib.sha256(
        json.dumps([recorded.measurement_id, "unused", "judge", recorded.definition_key]).encode()
    ).hexdigest()
    origin = tmp_path / "original-worktree" / "receipts"
    with eval_receipts.publication_receipt(origin, key) as receipt:
        receipt.write(eval_receipts.PublicationReceipt(key=key, evaluation_id="eval-id"))
        before = receipt.path.read_bytes()
    copied = tmp_path / "copied-worktree"
    copied.mkdir()
    monkeypatch.chdir(copied)
    calls = fake_boundary(monkeypatch, list_hook=lambda _: [], run_list_hook=lambda _: [])
    with pytest.raises(foundry.FoundryEvalError, match="Legacy publication origin is unknown"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    assert calls == []
    assert (origin / f"{key}.json").read_bytes() == before
    assert not list(foundry.RECEIPT_DIRECTORY.glob("*.json"))
    assert not foundry.LEGACY_RECEIPT_DIRECTORY.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_existing_legacy_origin_remains_locked_before_authentication(monkeypatch, explicit):
    recorded = publication()
    key = hashlib.sha256(
        json.dumps([recorded.measurement_id, "unused", "judge", recorded.definition_key]).encode()
    ).hexdigest()
    origin = foundry.LEGACY_RECEIPT_DIRECTORY
    calls = fake_boundary(monkeypatch)
    with eval_receipts.publication_receipt(origin, key) as receipt:
        receipt.write(eval_receipts.PublicationReceipt(key=key, evaluation_id="eval-id"))
        with pytest.raises(foundry.FoundryEvalError):
            foundry.publish(
                recorded,
                endpoint="unused",
                model="judge",
                legacy_directory=origin if explicit else None,
            )
    assert calls == []
    assert not list(foundry.RECEIPT_DIRECTORY.glob("*.json"))


def test_explicit_original_pending_import_never_creates_on_empty_remote_listing(
    monkeypatch, tmp_path
):
    recorded = publication().model_copy(update={"coordination": None})
    key = hashlib.sha256(
        json.dumps([recorded.measurement_id, "unused", "judge", recorded.definition_key]).encode()
    ).hexdigest()
    origin = tmp_path / "original-evidence"
    with eval_receipts.publication_receipt(origin, key) as receipt:
        receipt.write(eval_receipts.PublicationReceipt(key=key, evaluation_id="eval-id"))
        before = receipt.path.read_bytes()
    calls = fake_boundary(
        monkeypatch,
        existing=[existing_suite(recorded)],
        list_hook=lambda _: [],
        run_list_hook=lambda _: [],
    )
    with pytest.raises(foundry.FoundryEvalError, match="outcome is unknown"):
        foundry.publish(recorded, endpoint="unused", model="judge", legacy_directory=origin)
    assert calls == []
    assert (foundry.RECEIPT_DIRECTORY / f"{key}.json").read_bytes() == before


def test_unavailable_legacy_origin_fails_before_authentication(monkeypatch, tmp_path):
    def forbidden():
        pytest.fail("Unknown legacy origin must not authenticate or submit.")

    monkeypatch.setattr(foundry, "DefaultAzureCredential", forbidden)
    recorded = publication().model_copy(update={"coordination": None})
    missing = tmp_path / "unavailable-origin"
    with pytest.raises(foundry.FoundryEvalError, match="unavailable"):
        foundry.publish(recorded, endpoint="unused", model="judge", legacy_directory=missing)
    assert not missing.exists()
    missing.mkdir()
    with pytest.raises(foundry.FoundryEvalError, match="unavailable"):
        foundry.publish(recorded, endpoint="unused", model="judge", legacy_directory=missing)
    assert not list(missing.iterdir())
    with pytest.raises(foundry.FoundryEvalError, match="Legacy publication origin is unknown"):
        foundry.publish(recorded, endpoint="unused", model="judge")


def test_positive_legacy_run_evidence_resumes_only_the_original_measurement(monkeypatch, tmp_path):
    modern = publication()
    calls = fake_boundary(monkeypatch, run_list_hook=lambda _: [])
    foundry.publish(modern, endpoint="unused", model="judge")
    key = hashlib.sha256(
        json.dumps([modern.measurement_id, "unused", "judge", modern.definition_key]).encode()
    ).hexdigest()
    with eval_receipts.publication_receipt(foundry.RECEIPT_DIRECTORY, key) as shared:
        receipt = shared.read()
        assert receipt is not None
        origin = tmp_path / "original-evidence"
        with eval_receipts.publication_receipt(origin, key) as legacy:
            legacy.write(receipt)
        shared.clear()
    recorded = modern.model_copy(update={"coordination": None})
    assert foundry.publish(
        recorded, endpoint="unused", model="judge", legacy_directory=origin
    ).endswith("/report")
    assert sum(name == "run" for name, _ in calls) == 1


def test_positive_origin_input_cannot_substitute_another_measurement(monkeypatch, tmp_path):
    other = publication()
    calls = fake_boundary(monkeypatch, run_list_hook=lambda _: [])
    foundry.publish(other, endpoint="unused", model="judge")
    recorded = publication().model_copy(update={"coordination": None}, deep=True)
    recorded.rows[0].case_id = "different-measurement"
    key = hashlib.sha256(
        json.dumps([recorded.measurement_id, "unused", "judge", recorded.definition_key]).encode()
    ).hexdigest()
    origin = tmp_path / "original-evidence"
    with eval_receipts.publication_receipt(origin, key) as receipt:
        receipt.write(
            eval_receipts.PublicationReceipt(key=key, evaluation_id="eval-id", run_id="run-id")
        )
    with pytest.raises(foundry.FoundryEvalError, match="conflicts with the frozen measurement"):
        foundry.publish(recorded, endpoint="unused", model="judge", legacy_directory=origin)
    assert sum(name == "run" for name, _ in calls) == 1


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.parametrize("creation", ["suite", "run"])
def test_confirmed_creation_rejection_allows_retry(monkeypatch, status, creation):
    error = APIStatusError(
        "confirmed rejection",
        response=Response(status, request=Request("POST", "/evals")),
        body=None,
    )
    calls = (
        fake_boundary(monkeypatch, evaluation_error=[error, None])
        if creation == "suite"
        else fake_boundary(monkeypatch, create_error=[error, None])
    )
    recorded = publication()
    with pytest.raises(foundry.FoundryEvalError, match="confirmed rejection"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    directory = foundry.SUITE_DIRECTORY if creation == "suite" else foundry.RECEIPT_DIRECTORY
    assert not list(directory.glob("*.json"))
    assert foundry.publish(recorded, endpoint="unused", model="judge").endswith("/report")
    name = "evaluation" if creation == "suite" else "run"
    assert sum(call == name for call, _ in calls) == 2


@pytest.mark.parametrize("creation", ["suite", "run"])
def test_ambiguous_server_failure_does_not_clear_pending(monkeypatch, creation):
    error = APIStatusError(
        "ambiguous server failure",
        response=Response(500, request=Request("POST", "/evals")),
        body=None,
    )
    calls = (
        fake_boundary(monkeypatch, evaluation_error=error)
        if creation == "suite"
        else fake_boundary(monkeypatch, create_error=error)
    )
    with pytest.raises(foundry.FoundryEvalError, match="ambiguous server failure"):
        foundry.publish(publication(), endpoint="unused", model="judge")
    with pytest.raises(foundry.FoundryEvalError, match="outcome is unknown"):
        foundry.publish(publication(), endpoint="unused", model="judge")
    name = "evaluation" if creation == "suite" else "run"
    assert sum(call == name for call, _ in calls) == 1


@pytest.mark.parametrize("second_model", ["judge", "other-judge"])
def test_concurrent_measurements_in_separate_directories_create_one_suite(
    monkeypatch, tmp_path, second_model
):
    context = threading.local()
    first_creating = threading.Event()
    second_attempting = threading.Event()
    second_listed = threading.Event()
    allow_create = threading.Event()
    original_receipt = eval_receipts.publication_receipt

    @contextmanager
    def separate_receipts(_directory, key):
        with original_receipt(tmp_path / f"run-{context.index}" / "receipts", key) as receipt:
            if context.index == 1:
                second_attempting.set()
            yield receipt

    def list_hook(evaluations):
        snapshot = list(evaluations)
        if context.index == 1:
            second_listed.set()
        return snapshot

    def create_hook():
        if context.index == 0:
            first_creating.set()
            assert allow_create.wait(5)

    monkeypatch.setattr(foundry, "publication_receipt", separate_receipts)
    calls = fake_boundary(monkeypatch, list_hook=list_hook, create_hook=create_hook)

    def submit(index):
        context.index = index
        recorded = publication()
        recorded.rows[0].case_id = f"case-{index}"
        return foundry.publish(
            recorded, endpoint="unused", model="judge" if index == 0 else second_model
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(submit, 0)
        try:
            assert first_creating.wait(5)
            second = executor.submit(submit, 1)
            assert second_attempting.wait(5)
            second_listed.wait(0.25)
        finally:
            allow_create.set()
        assert first.result(timeout=5).endswith("/report")
        if second_model == "judge":
            assert second.result(timeout=5).endswith("/report")
        else:
            with pytest.raises(foundry.FoundryEvalError, match="schema differs"):
                second.result(timeout=5)
    assert sum(name == "evaluation" for name, _ in calls) == 1
    assert sum(name == "run" for name, _ in calls) == (2 if second_model == "judge" else 1)


def test_canonical_suite_cache_handles_stale_remote_listing(monkeypatch):
    calls = fake_boundary(monkeypatch, list_hook=lambda _: [])
    first = publication()
    second = publication()
    second.rows[0].case_id = "another-case"
    foundry.publish(first, endpoint="unused", model="judge")
    foundry.publish(second, endpoint="unused", model="judge")
    assert sum(name == "evaluation" for name, _ in calls) == 1
    assert sum(name == "run" for name, _ in calls) == 2


@pytest.mark.parametrize("visible", [False, True])
def test_ambiguous_suite_creation_never_submits_a_duplicate(monkeypatch, visible):
    calls = fake_boundary(
        monkeypatch,
        list_hook=None if visible else lambda _: [],
        evaluation_error=OSError("suite response lost"),
    )
    recorded = publication()
    with pytest.raises(foundry.FoundryEvalError, match="suite response lost"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    if visible:
        assert foundry.publish(recorded, endpoint="unused", model="judge").endswith("/report")
    else:
        with pytest.raises(foundry.FoundryEvalError, match="suite creation outcome is unknown"):
            foundry.publish(recorded, endpoint="unused", model="judge")
    assert sum(name == "evaluation" for name, _ in calls) == 1
    assert sum(name == "run" for name, _ in calls) == int(visible)


def test_user_level_suite_state_is_private_and_contains_no_measurements(monkeypatch):
    fake_boundary(monkeypatch)
    foundry.publish(publication(), endpoint="unused", model="judge")
    assert stat.S_IMODE(foundry.SUITE_DIRECTORY.stat().st_mode) == 0o700
    for path in foundry.SUITE_DIRECTORY.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if path.suffix == ".json":
            assert set(json.loads(path.read_text())) == {
                "key",
                "definition_key",
                "judge_model",
                "evaluation_id",
            }


def test_published_rows_preserve_provenance_without_local_grading_fields(monkeypatch):
    saved = publication()
    before = saved.model_dump_json()
    measurement_id = saved.measurement_id
    calls = fake_boundary(monkeypatch)
    assert foundry.publish(saved, endpoint="unused", model="judge") == "https://example.test/report"
    payload = next(value for name, value in calls if name == "run")
    assert payload["metadata"] == {
        **saved.metadata,
        "csai_measurement": saved.measurement_id,
    }
    row = payload["data_source"]["source"]["content"][0]["item"]
    schema = next(value for name, value in calls if name == "evaluation")["data_source_config"][
        "item_schema"
    ]
    assert {"scores", "failure", "observations_digest"}.isdisjoint(row)
    assert {"scores", "failure", "observations_digest"}.isdisjoint(schema["properties"])
    assert row["ground_truth"] == {"failure_mode_id": "FM-01"}
    assert row["source"] == "synthetic"
    assert row["cohort"] == "regression"
    assert saved.model_dump_json() == before
    assert saved.measurement_id == measurement_id
    criteria = next(value for name, value in calls if name == "evaluation")["testing_criteria"]
    assert {criterion["name"] for criterion in criteria} == {
        "task_adherence",
        "intent_resolution",
        "coherence",
        "tool_call_accuracy",
    }
    assert len(criteria) == 4
    for criterion in criteria:
        name = criterion["name"]
        assert criterion == {
            "type": "azure_ai_evaluator",
            "name": name,
            "evaluator_name": f"builtin.{name}",
            "initialization_parameters": {"deployment_name": "judge"},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                **(
                    {"tool_definitions": "{{item.tool_definitions}}"} if name != "coherence" else {}
                ),
                **({"tool_calls": "{{item.tool_calls}}"} if name == "tool_call_accuracy" else {}),
            },
        }


def test_different_frozen_observations_do_not_change_judges_definition(monkeypatch):
    calls = fake_boundary(monkeypatch)
    foundry.publish(publication(), endpoint="unused", model="judge")
    other = publication(observations_digest="different-frozen-observations")
    foundry.publish(other, endpoint="unused", model="judge")
    assert sum(name == "evaluation" for name, _ in calls) == 1
    assert sum(name == "run" for name, _ in calls) == 2


@pytest.mark.parametrize("judge", ["task_adherence", "intent_resolution", "tool_call_accuracy"])
def test_agent_judges_map_real_calls_and_pinned_definitions(monkeypatch, judge):
    calls = [
        {"type": "tool_call", "name": "get_machine_context", "arguments": {"machine_id": "M-0001"}}
    ]
    definitions = [{"type": "function", "name": "get_machine_context", "parameters": {}}]
    recorded = publication(tool_calls=calls, tool_definitions=definitions)
    sdk_calls = fake_boundary(monkeypatch)
    foundry.publish(recorded, endpoint="unused", model="judge")
    payload = next(value for name, value in sdk_calls if name == "run")
    row = payload["data_source"]["source"]["content"][0]["item"]
    assert row["tool_calls"] == calls
    assert row["tool_definitions"] == definitions
    criteria = next(value for name, value in sdk_calls if name == "evaluation")["testing_criteria"]
    criterion = next(item for item in criteria if item["name"] == judge)
    assert criterion["data_mapping"] == {
        "query": "{{item.query}}",
        "response": "{{item.response}}",
        "tool_definitions": "{{item.tool_definitions}}",
        **({"tool_calls": "{{item.tool_calls}}"} if judge == "tool_call_accuracy" else {}),
    }


def test_reuses_suite_evaluation_and_keeps_independent_run_metadata(monkeypatch):
    recorded = publication()
    calls = fake_boundary(
        monkeypatch,
        existing=[
            SimpleNamespace(
                id="existing-eval",
                metadata={
                    "csai_suite": "rca",
                    "definition_key": recorded.definition_key,
                    "judge_model": "judge",
                },
            )
        ],
    )
    foundry.publish(recorded, endpoint="unused", model="judge")
    assert [name for name, _ in calls] == ["run"]
    assert calls[0][1]["eval_id"] == "existing-eval"


@pytest.mark.parametrize("schema", [2, 3, 4])
@pytest.mark.parametrize("cached", [False, True])
def test_judges_use_a_new_definition_without_migrating_old_evaluations(monkeypatch, schema, cached):
    recorded = publication()
    previous_definition = {
        "metrics": {
            "calibration_score" if name == "calibration" and schema == 4 else name: (
                "decrease" if name == "calibration" and schema < 4 else "increase"
            )
            for name in ("calibration", "hit_at_1")
        },
        "judges": foundry.BUILTIN_EVALUATORS,
        "schema": schema,
    }
    previous_key = hashlib.sha256(
        json.dumps(previous_definition, sort_keys=True).encode()
    ).hexdigest()
    old_evaluation = SimpleNamespace(
        id="existing-eval",
        metadata={
            "csai_suite": "rca",
            "definition_key": previous_key,
            "judge_model": "judge",
        },
    )
    old_metadata = old_evaluation.metadata.copy()
    calls = fake_boundary(
        monkeypatch,
        existing=[old_evaluation],
    )
    old_paths = {}
    if cached:
        key = hashlib.sha256(json.dumps(["unused", recorded.suite]).encode()).hexdigest()
        with eval_receipts.suite_receipt(foundry.SUITE_DIRECTORY, key) as cache:
            cache.write(
                eval_receipts.SuiteReceipt(
                    key=key,
                    definition_key=previous_key,
                    judge_model="judge",
                    evaluation_id="existing-eval",
                )
            )
            old_paths[cache.path] = cache.path.read_bytes()
        key = hashlib.sha256(
            json.dumps([recorded.measurement_id, "unused", "judge"]).encode()
        ).hexdigest()
        with eval_receipts.publication_receipt(foundry.RECEIPT_DIRECTORY, key) as receipt:
            receipt.write(
                eval_receipts.PublicationReceipt(
                    key=key, evaluation_id="existing-eval", run_id="old-run"
                )
            )
            old_paths[receipt.path] = receipt.path.read_bytes()
    foundry.publish(recorded, endpoint="unused", model="judge")
    foundry.publish(recorded, endpoint="unused", model="judge")
    assert sum(name == "evaluation" for name, _ in calls) == 1
    assert sum(name == "run" for name, _ in calls) == 1
    run = next(value for name, value in calls if name == "run")
    assert run["eval_id"] != old_evaluation.id
    assert old_evaluation.metadata == old_metadata
    assert all(path.read_bytes() == before for path, before in old_paths.items())


@pytest.mark.parametrize(("status", "errored"), [("failed", 0), ("completed", 1), ("cancelled", 0)])
def test_service_and_item_failures_are_not_reported_as_success(monkeypatch, status, errored):
    fake_boundary(monkeypatch, status=status, errored=errored)
    with pytest.raises(foundry.FoundryEvalError, match="Foundry evaluation"):
        foundry.publish(publication(), endpoint="unused", model="judge")


def test_missing_tool_definitions_are_not_reconstructed():
    with pytest.raises(foundry.FoundryEvalError, match="not captured"):
        foundry.publish(
            publication(tool_calls=[{"name": "get_machine_context"}]),
            endpoint="unused",
            model="judge",
        )


@pytest.mark.parametrize("calls", [[], [{"name": "lookup_error_code"}]])
def test_incomplete_traces_fail_before_authentication(calls):
    recorded = publication(
        tool_calls=calls,
        tool_definitions=[{"type": "function", "name": "lookup_error_code"}],
    )
    recorded.rows[0].tool_trace_complete = False
    with pytest.raises(foundry.FoundryEvalError, match="incomplete"):
        foundry.publish(recorded, endpoint="unused", model="judge")


@pytest.mark.parametrize("status", ["queued", "in_progress"])
@pytest.mark.parametrize("visible", [False, True])
def test_timeout_resumes_the_same_run_without_more_judge_calls(monkeypatch, status, visible):
    recorded = publication()
    original = recorded.model_dump_json()
    runs = []
    calls = fake_boundary(
        monkeypatch, status=status, run_state=runs, run_list_hook=None if visible else lambda _: []
    )
    monkeypatch.setattr(foundry, "TIMEOUT_S", 0)
    for _ in range(2):
        with pytest.raises(foundry.FoundryEvalPending, match="still running") as pending:
            foundry.publish(recorded, endpoint="unused", model="judge")
        assert pending.value.run_id == "run-id"
        assert pending.value.report_url == "https://example.test/report"
    assert len(runs) == 1
    runs[0].status = "completed"
    assert foundry.publish(recorded, endpoint="unused", model="judge").endswith("/report")
    assert sum(name == "run" for name, _ in calls) == 1
    assert any(name == "retrieve" for name, _ in calls)
    assert recorded.model_dump_json() == original


def test_remote_measurement_lookup_reuses_run_without_local_receipt(monkeypatch):
    recorded = publication()
    calls = fake_boundary(monkeypatch)
    foundry.publish(recorded, endpoint="unused", model="judge")
    for receipt in foundry.RECEIPT_DIRECTORY.glob("*.json"):
        receipt.unlink()
    foundry.publish(recorded, endpoint="unused", model="judge")
    assert sum(name == "run" for name, _ in calls) == 1


def test_ambiguous_submission_recovers_via_remote_identity_without_resubmitting(monkeypatch):
    recorded = publication()
    calls = fake_boundary(monkeypatch, create_error=OSError("response lost after submission"))
    with pytest.raises(foundry.FoundryEvalError, match="response lost"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    assert foundry.publish(recorded, endpoint="unused", model="judge").endswith("/report")
    assert sum(name == "run" for name, _ in calls) == 1


def test_unknown_submission_blocks_retry_if_remote_run_is_not_visible(monkeypatch):
    recorded = publication()
    runs = []
    calls = fake_boundary(monkeypatch, run_state=runs, create_error=OSError("response lost"))
    with pytest.raises(foundry.FoundryEvalError):
        foundry.publish(recorded, endpoint="unused", model="judge")
    runs.clear()
    with pytest.raises(foundry.FoundryEvalError, match="outcome is unknown"):
        foundry.publish(recorded, endpoint="unused", model="judge")
    assert sum(name == "run" for name, _ in calls) == 1


def test_receipts_are_private_and_contain_no_measured_rows(monkeypatch):
    recorded = publication()
    fake_boundary(monkeypatch)
    foundry.publish(recorded, endpoint="unused", model="judge")
    directory = foundry.RECEIPT_DIRECTORY
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if path.suffix == ".json":
            assert set(json.loads(path.read_text())) == {"key", "evaluation_id", "run_id"}
