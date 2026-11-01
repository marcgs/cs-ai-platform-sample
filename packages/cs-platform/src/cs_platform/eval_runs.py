"""Durable, offline eval run records. The journal, not an export, is authoritative."""

import hashlib
import html
import json
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from cs_platform.episodes import Episode
from cs_platform.eval_reporting import RunMetadata, artifact_paths, validate_artifact_destinations
from cs_platform.evals import (
    CaseResult,
    EvalCase,
    EvalPersistenceError,
    EvalSuite,
    RunOutput,
    SuiteResult,
    Thresholds,
    assign_splits,
)


class CaseRunKey(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    repeat: int = Field(ge=1)


class RunManifest(BaseModel):
    """Frozen selection and gate configuration, readable without importing an agent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    suite: str
    cases: tuple[EvalCase, ...]
    cohorts: dict[str, str] = Field(default_factory=dict[str, str])
    thresholds: Thresholds
    gate_case_ids: frozenset[str] | None
    metadata: RunMetadata
    result_filename: str
    concurrency: int = Field(ge=1)
    retries: int = Field(default=2, ge=0)
    backoff_s: float = Field(default=20.0, ge=0)


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Started(_Event):
    kind: Literal["started"] = "started"
    key: CaseRunKey


class AttemptStarted(_Event):
    kind: Literal["attempt_started"] = "attempt_started"
    key: CaseRunKey
    attempt: int = Field(ge=1)


class AttemptFinished(_Event):
    kind: Literal["attempt_finished"] = "attempt_finished"
    key: CaseRunKey
    output: RunOutput


class CaseFinished(_Event):
    kind: Literal["case_finished"] = "case_finished"
    result: CaseResult


class EpisodeCaptured(_Event):
    kind: Literal["episode"] = "episode"
    key: CaseRunKey | None
    attempt: int | None
    episode: Episode


class Finished(_Event):
    kind: Literal["finished"] = "finished"
    status: Literal["complete", "incomplete"]
    error: str | None = None


type RunEvent = Annotated[
    Started | AttemptStarted | AttemptFinished | CaseFinished | EpisodeCaptured | Finished,
    Field(discriminator="kind"),
]
_event_adapter = TypeAdapter[RunEvent](RunEvent)


class RunRecord(BaseModel):
    """Public disk snapshot for reporting and publishing; missing episodes stay missing."""

    model_config = ConfigDict(extra="forbid")

    manifest: RunManifest
    events: list[RunEvent]
    result: SuiteResult
    status: Literal["complete", "incomplete"]
    never_started: list[CaseRunKey]
    interrupted: list[CaseRunKey]
    failures: list[str]
    journal_warning: str | None = None

    @property
    def episodes(self) -> list[Episode]:
        return [event.episode for event in self.events if isinstance(event, EpisodeCaptured)]

    @property
    def attempts(self) -> list[AttemptFinished]:
        return [event for event in self.events if isinstance(event, AttemptFinished)]

    def suite(self) -> EvalSuite:
        """Recover frozen gates and truth, with no evaluators or model access."""
        return EvalSuite(
            self.manifest.suite,
            self.manifest.cases,
            self.manifest.thresholds,
            (),
            gate_case_ids=self.manifest.gate_case_ids,
        )


def run_directory(output: Path) -> Path:
    return output.parent / f"{output.stem}.run"


def validate_run_destinations(output: Path, *, episodes_path: Path | None = None) -> None:
    """Reserve the journal as well as legacy artifacts, before any target runs."""
    validate_artifact_destinations(output, episodes_path=episodes_path)
    journal = run_directory(output).resolve()
    if journal.exists() or run_directory(output).is_symlink():
        raise FileExistsError(f"artifact destination already exists: {journal}")
    for path in (*artifact_paths(output), *((episodes_path,) if episodes_path else ())):
        destination = path.resolve()
        if (
            destination == journal
            or destination in journal.parents
            or journal in destination.parents
        ):
            raise ValueError(f"artifact destinations overlap: {path}")


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, text: str, *, append: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing symlink artifact destination: {path}")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_EXCL)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _replace(path: Path, text: str) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing symlink artifact destination: {path}")
    pending = path.with_name(f".{path.name}.{uuid4().hex}.pending")
    created = False
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            created = True
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
        _sync_directory(path.parent)
    finally:
        if created and pending.exists():
            pending.unlink()


def _mkdir(path: Path, *, parents: bool = False) -> None:
    if parents and not path.parent.is_dir():
        _mkdir(path.parent, parents=True)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not parents or not path.is_dir():
            raise
    else:
        _sync_directory(path.parent)


def _transcript_filename(result: CaseResult) -> str:
    identity = hashlib.sha256(result.case_id.encode()).hexdigest()[:16]
    return f"{identity}-{result.repeat}.json"


def _transcript(manifest: RunManifest, result: CaseResult) -> str:
    case = next(case for case in manifest.cases if case.id == result.case_id)
    return (
        json.dumps(
            {"case": case.model_dump(mode="json"), **result.model_dump(mode="json")}, indent=2
        )
        + "\n"
    )


def _cohort(suite: EvalSuite, case: EvalCase) -> str:
    declared = case.model_dump().get("cohort")
    if isinstance(declared, str):
        return declared
    return (
        "original" if suite.gate_case_ids is None or case.id in suite.gate_case_ids else "challenge"
    )


class RunWriter:
    """Single-process append writer. Each event is flushed and fsynced before returning."""

    def __init__(
        self, suite: EvalSuite, output: Path, metadata: RunMetadata, *, concurrency: int
    ) -> None:
        validate_run_destinations(output)
        self.output = output
        self.directory = run_directory(output)
        self.manifest = RunManifest(
            suite=suite.name,
            cases=assign_splits(suite.cases),
            cohorts={case.id: _cohort(suite, case) for case in suite.cases},
            thresholds=suite.thresholds,
            gate_case_ids=suite.gate_case_ids,
            metadata=metadata,
            result_filename=output.name,
            concurrency=concurrency,
        )
        self._current = ContextVar[tuple[CaseRunKey, int] | None]("eval_attempt", default=None)
        self._journal_failed = False
        _mkdir(output.parent, parents=True)
        _mkdir(self.directory)
        _mkdir(artifact_paths(output)[3])
        _write(self.directory / "manifest.json", self.manifest.model_dump_json(indent=2) + "\n")
        for path in (self.directory / "events.jsonl", self.directory / "episodes.jsonl", output):
            _write(path, "")

    def append(self, event: RunEvent) -> None:
        if self._journal_failed:
            raise EvalPersistenceError("Journal write previously failed; no further appends.")
        try:
            _write(self.directory / "events.jsonl", event.model_dump_json() + "\n", append=True)
        except BaseException as error:
            self._journal_failed = True
            if isinstance(error, Exception):
                raise EvalPersistenceError("Could not append the eval journal.") from error
            raise

    def start(self, case: EvalCase, repeat: int) -> None:
        self.append(Started(key=CaseRunKey(case_id=case.id, repeat=repeat)))

    def start_attempt(self, case: EvalCase, repeat: int, attempt: int) -> None:
        key = CaseRunKey(case_id=case.id, repeat=repeat)
        self._current.set((key, attempt))
        self.append(AttemptStarted(key=key, attempt=attempt))

    def attempt(self, case: EvalCase, repeat: int, output: RunOutput) -> None:
        self.append(AttemptFinished(key=CaseRunKey(case_id=case.id, repeat=repeat), output=output))

    def episode(self, episode: Episode) -> None:
        current = self._current.get()
        self.append(
            EpisodeCaptured(
                key=current[0] if current else None,
                attempt=current[1] if current else None,
                episode=episode,
            )
        )
        try:
            _write(self.directory / "episodes.jsonl", episode.model_dump_json() + "\n", append=True)
        except Exception as error:
            raise EvalPersistenceError("Could not export the captured episode.") from error

    def completed(self, result: CaseResult) -> None:
        self.append(CaseFinished(result=result))
        _write(self.output, json.dumps(result.model_dump(mode="json")) + "\n", append=True)
        _write(
            artifact_paths(self.output)[3] / _transcript_filename(result),
            _transcript(self.manifest, result),
        )

    def finish(self, *, error: BaseException | None = None) -> None:
        self.append(
            Finished(
                status="complete" if error is None else "incomplete",
                error=type(error).__name__ if error is not None else None,
            )
        )

    def finalize(self) -> RunRecord:
        """Export the prospective complete snapshot before committing its final marker."""
        record = load_run(self.directory)
        if record.never_started or record.interrupted:
            raise ValueError("Cannot finalize missing case-runs.")
        if self._journal_failed or record.journal_warning:
            raise EvalPersistenceError("Cannot finalize a failed journal.")
        record.status = "complete"
        record.failures = record.result.failures(record.manifest.thresholds)
        _export_record(self.directory, record)
        self.finish()
        return load_run(self.directory)


def _locate(results_dir: Path) -> Path:
    if results_dir.is_file():
        return run_directory(results_dir)
    if (results_dir / "manifest.json").is_file():
        return results_dir
    if not results_dir.is_dir() and run_directory(results_dir).is_dir():
        return run_directory(results_dir)
    matches = sorted(results_dir.glob("*.run/manifest.json"))
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one durable .run directory; pass that directory explicitly"
        )
    return matches[0].parent


def load_run(results_dir: Path) -> RunRecord:
    """Read schema v1 records, ignoring only an uncommitted final journal fragment.

    Legacy exports alone cannot prove completion or recover real episodes and are rejected.
    """
    directory = _locate(results_dir)
    manifest = RunManifest.model_validate_json((directory / "manifest.json").read_text("utf-8"))
    if (
        Path(manifest.result_filename).name != manifest.result_filename
        or manifest.result_filename in {"", ".", ".."}
        or run_directory(directory.parent / manifest.result_filename).resolve()
        != directory.resolve()
    ):
        raise ValueError("result filename must be a basename")
    events: list[RunEvent] = []
    lines = (directory / "events.jsonl").read_bytes().split(b"\n")
    warning = "Uncommitted final journal fragment ignored." if lines[-1] else None
    for line in lines[:-1]:
        events.append(_event_adapter.validate_json(line))
    expected = [
        CaseRunKey(case_id=case.id, repeat=repeat)
        for case in manifest.cases
        for repeat in range(1, manifest.metadata.repeats + 1)
    ]
    started = {event.key for event in events if isinstance(event, Started)}
    completed = {
        CaseRunKey(case_id=event.result.case_id, repeat=event.result.repeat): event.result
        for event in events
        if isinstance(event, CaseFinished)
    }
    if not started <= set(expected) or not completed.keys() <= started:
        raise ValueError("journal contains case-runs outside the frozen selection")
    if len(completed) != sum(isinstance(event, CaseFinished) for event in events):
        raise ValueError("journal contains repeated completed case-runs")
    if any(
        result.gated != (manifest.gate_case_ids is None or result.case_id in manifest.gate_case_ids)
        for result in completed.values()
    ):
        raise ValueError("journal result conflicts with the frozen regression gate")
    result = SuiteResult(
        suite=manifest.suite,
        cases=[completed[key] for key in expected if key in completed],
        minimum_score_metrics=frozenset(manifest.thresholds.minimums),
    )
    complete = (
        len(completed) == len(expected)
        and bool(events)
        and isinstance(events[-1], Finished)
        and events[-1].status == "complete"
        and warning is None
    )
    failures = result.failures(manifest.thresholds)
    if not complete:
        failures.insert(0, "Run incomplete; the regression gate cannot pass.")
    return RunRecord(
        manifest=manifest,
        events=events,
        result=result,
        status="complete" if complete else "incomplete",
        never_started=[key for key in expected if key not in started],
        interrupted=[key for key in expected if key in started and key not in completed],
        failures=failures,
        journal_warning=warning,
    )


read_run = load_run


def rebuild_report(results_dir: Path) -> RunRecord:
    """Rebuild derived exports, summary and escaped HTML from disk, never running a case."""
    directory = _locate(results_dir)
    record = load_run(directory)
    return _export_record(directory, record)


def _export_record(directory: Path, record: RunRecord) -> RunRecord:
    output = directory.parent / record.manifest.result_filename
    _, summary_path, html_path, transcripts = artifact_paths(output)
    if transcripts.is_symlink():
        raise ValueError(f"refusing symlink artifact destination: {transcripts}")
    _mkdir(transcripts, parents=True)
    result = record.result
    summary = {
        "run": record.manifest.metadata.model_dump(mode="json"),
        "suite": result.suite,
        "status": record.status,
        "case_count": len({case.case_id for case in result.cases}),
        "case_runs": len(result.cases),
        "expected_case_runs": len(record.manifest.cases) * record.manifest.metadata.repeats,
        "never_started": [key.model_dump() for key in record.never_started],
        "interrupted": [key.model_dump() for key in record.interrupted],
        "attempts": len(record.attempts),
        "quality_case_runs": len(result.quality_cases),
        "gate_case_ids": sorted({case.case_id for case in result.cases if case.gated}),
        "minimum_score_metrics": sorted(result.minimum_score_metrics),
        "metrics": result.metrics,
        "intervals": result.intervals,
        "gate_metrics": result.gate_metrics,
        "gate_intervals": result.gate_intervals,
        "groups": result.groups,
        "failures": record.failures,
        "warnings": result.warnings(record.manifest.thresholds)
        + ([record.journal_warning] if record.journal_warning else []),
        "bootstrap": {
            "method": "hierarchical case then repeat percentile 95%",
            "samples": result.bootstrap_samples,
            "seed": result.bootstrap_seed,
        },
    }
    sections: list[str] = []
    for case in result.cases:
        filename = _transcript_filename(case)
        rendered = _transcript(record.manifest, case)
        link = html.escape(quote(f"./{transcripts.name}/{filename}", safe="/"), quote=True)
        label = html.escape(f"{case.case_id} repeat {case.repeat}")
        sections.append(
            f'<details><summary><a href="{link}">{label}</a></summary>'
            f"<pre>{html.escape(rendered)}</pre></details>"
        )
    _replace(summary_path, json.dumps(summary, indent=2) + "\n")
    title = html.escape(result.suite)
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; base-uri 'none'; form-action 'none'\">"
        f"<title>{title} evaluation</title><body><h1>{title} evaluation</h1>"
        "<p>Private synthetic evaluation data. Only regression cases determine the gate.</p>"
        f"<pre>{html.escape(json.dumps(summary, indent=2))}</pre>"
        + "".join(sections)
        + "</body></html>\n"
    )
    _replace(html_path, page)
    _replace(output, result.to_jsonl() if result.cases else "")
    _replace(
        directory / "episodes.jsonl",
        "".join(episode.model_dump_json() + "\n" for episode in record.episodes),
    )
    for case in result.cases:
        _replace(transcripts / _transcript_filename(case), _transcript(record.manifest, case))
    return record
