"""Evaluation harness: run an agent over a versioned case manifest, score it, and gate on it.

An agent's suite is data plus code: ``cases.jsonl`` (one :class:`EvalCase` per line),
``thresholds.yaml`` (minimum mean per metric) and evaluators, plain functions that score one
case's output. A *target* runs one case against some deployment of the agent (in-process,
hosted, ...), so the same suite gates local changes and deployed versions alike.
"""

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from statistics import mean
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cs_platform.episodes import ToolCall

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path


type Split = Literal["train", "test"]
type Category = Literal[
    "clean",
    "overlapping",
    "no_fault_found",
    "out_of_catalog",
    "missing_machine",
    "injection",
    "sensor_fault",
    "data_gap",
    "nuisance_alarm",
]


class EvalTruth(BaseModel):
    """Causal ground truth supplied by a dataset, never inferred from an agent answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Category
    decisive_refs: tuple[str, ...] = ()
    acceptable_failure_modes: tuple[str, ...] = ()
    ruled_out_failure_modes: tuple[str, ...] = ()
    confirming_checks: tuple[str, ...] = ()
    injection_markers: tuple[str, ...] = ()


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    input: str = Field(description="The message sent to the agent.")
    expected: dict[str, str] = Field(description="Ground truth, interpreted by the evaluators.")
    truth: EvalTruth | None = None
    split: Split | None = None


def assign_splits(cases: tuple[EvalCase, ...]) -> tuple[EvalCase, ...]:
    """Stratify machines approximately 2:1 by category using a fixed salted hash.

    Explicit manifest assignments are frozen on append. For a new stratum, rank machines
    by hash and reserve about one third for test. Shared machines remain in one split,
    even when that constrains balancing another category.
    """
    assignments: dict[str, Split] = {}
    for case in cases:
        machine = case.expected.get("machine_id", case.id)
        if case.split is not None:
            previous = assignments.setdefault(machine, case.split)
            if previous != case.split:
                raise ValueError(f"machine {machine} occurs in both splits")
    strata: dict[str, set[str]] = {}
    for case in cases:
        machine = case.expected.get("machine_id", case.id)
        strata.setdefault(case.truth.category if case.truth else "clean", set()).add(machine)
    for category in sorted(strata):
        machines = sorted(
            strata[category],
            key=lambda machine: (
                hashlib.sha256(f"cs-platform-eval-split-v1:{machine}".encode()).digest(),
                machine,
            ),
        )
        needed = max(
            0,
            round(len(machines) / 3)
            - sum(assignments.get(machine) == "test" for machine in machines),
        )
        unassigned = [machine for machine in machines if machine not in assignments]
        for index, machine in enumerate(unassigned):
            assignments[machine] = "test" if index < needed else "train"
    return tuple(
        case.model_copy(update={"split": assignments[case.expected.get("machine_id", case.id)]})
        for case in cases
    )


class RunError(BaseModel):
    """Structured failure independent of quality scores."""

    kind: Literal["plumbing", "unparseable", "wrong_answer"]
    code: str
    detail: str | None = None


class RunOutput(BaseModel):
    """What a target observed when running one case."""

    text: str | None = None
    value: Any = Field(default=None, description="Parsed structured output, if any.")
    tool_calls: list[str] = Field(default_factory=list[str])
    tool_trace: list[ToolCall] = Field(default_factory=list[ToolCall])
    tool_trace_complete: bool = False
    error: str | None = None
    failure: RunError | None = None
    duration_s: float = 0.0
    attempts: int = 1
    episode_id: str | None = None
    response_id: str | None = None


type Evaluator = Callable[[EvalCase, RunOutput], Mapping[str, float]]
type Target = Callable[[EvalCase], Awaitable[RunOutput]]


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimums: dict[str, float] = Field(description="Minimum mean score per metric.")


@dataclass(frozen=True)
class EvalSuite:
    name: str
    cases: tuple[EvalCase, ...]
    thresholds: Thresholds
    evaluators: tuple[Evaluator, ...]
    gate_case_ids: frozenset[str] | None = None

    @classmethod
    def from_files(
        cls,
        name: str,
        cases: Path,
        thresholds: Path,
        evaluators: tuple[Evaluator, ...],
        *,
        gate_case_ids: frozenset[str] | None = None,
    ) -> EvalSuite:
        lines = cases.read_text(encoding="utf-8").splitlines()
        return cls(
            name=name,
            cases=tuple(EvalCase.model_validate_json(line) for line in lines if line.strip()),
            thresholds=Thresholds.model_validate(yaml.safe_load(thresholds.read_text("utf-8"))),
            evaluators=evaluators,
            gate_case_ids=gate_case_ids,
        )


class CaseResult(BaseModel):
    case_id: str
    scores: dict[str, float]
    output: RunOutput
    repeat: int = 1
    input: str = ""
    category: str = "clean"
    split: Split | None = None
    gated: bool = True


class SuiteResult(BaseModel):
    suite: str
    cases: list[CaseResult]
    minimum_score_metrics: frozenset[str] = frozenset()
    bootstrap_samples: int = 2000
    bootstrap_seed: int = 42

    @property
    def metrics(self) -> dict[str, float]:
        """Quality means over applicable scores; plumbing is excluded."""
        return aggregate(self.quality_cases, zero_fill=self.minimum_score_metrics)

    @property
    def quality_cases(self) -> list[CaseResult]:
        return [case for case in self.cases if not is_plumbing(case.output)]

    @property
    def gate_metrics(self) -> dict[str, float]:
        return aggregate(
            [case for case in self.quality_cases if case.gated],
            zero_fill=self.minimum_score_metrics,
        )

    @property
    def intervals(self) -> dict[str, tuple[float, float]]:
        return bootstrap_intervals(
            self.quality_cases,
            samples=self.bootstrap_samples,
            seed=self.bootstrap_seed,
            zero_fill=self.minimum_score_metrics,
        )

    @property
    def gate_intervals(self) -> dict[str, tuple[float, float]]:
        return bootstrap_intervals(
            [case for case in self.quality_cases if case.gated],
            samples=self.bootstrap_samples,
            seed=self.bootstrap_seed,
            zero_fill=self.minimum_score_metrics,
        )

    @property
    def groups(self) -> dict[str, dict[str, dict[str, float]]]:
        return {
            field: {
                str(value): aggregate(
                    [case for case in self.quality_cases if str(getattr(case, field)) == value],
                    zero_fill=self.minimum_score_metrics,
                )
                for value in sorted({str(getattr(case, field)) for case in self.cases})
            }
            for field in ("category", "split")
        }

    @property
    def errored(self) -> list[str]:
        """Cases the target couldn't run, even after retries."""
        return [
            case.case_id
            for case in self.cases
            if case.gated
            and (
                case.output.error
                or (case.output.failure and case.output.failure.kind != "wrong_answer")
            )
        ]

    def failures(self, thresholds: Thresholds) -> list[str]:
        """Why the gate fails: errored cases first, then threshold violations."""
        metrics = aggregate(
            [case for case in self.quality_cases if case.gated],
            zero_fill=frozenset(thresholds.minimums),
        )
        failures: list[str] = []
        if self.errored:
            failures.append(f"{len(self.errored)} case(s) errored: {', '.join(self.errored)}")
        if not any(case.gated for case in self.cases) and self.cases:
            return failures
        failures.extend(
            f"{name}: {metrics.get(name, 0.0):.2f} < {minimum:.2f}"
            for name, minimum in thresholds.minimums.items()
            if metrics.get(name, 0.0) < minimum
        )
        return failures

    def warnings(self, thresholds: Thresholds) -> list[str]:
        """Flag saturated gates and uncertainty larger than the threshold margin."""
        warnings: list[str] = []
        gated = [case for case in self.quality_cases if case.gated]
        minimums = frozenset(thresholds.minimums)
        metrics = aggregate(gated, zero_fill=minimums)
        intervals = bootstrap_intervals(
            gated,
            samples=self.bootstrap_samples,
            seed=self.bootstrap_seed,
            zero_fill=minimums,
        )
        for name, minimum in thresholds.minimums.items():
            value = metrics.get(name)
            if value is None:
                continue
            if value >= 0.95:
                warnings.append(f"{name}: saturated gated mean ({value:.2f} >= 0.95)")
            low, high = intervals[name]
            if high - low > abs(value - minimum):
                warnings.append(f"{name}: CI width exceeds gap to threshold")
        if not any(case.gated for case in self.cases):
            warnings.append("No regression cases selected; results are informational, not a gate.")
        if any(not case.output.tool_trace_complete for case in self.cases):
            warnings.append("Some tool transcripts are incomplete; see per-run trace flags.")
        for category in sorted({case.category for case in self.cases}):
            splits = {case.split for case in self.cases if case.category == category}
            if splits != {"train", "test"}:
                warnings.append(f"category={category}: train/test stratum is incomplete")
        return warnings

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(case.model_dump(mode="json")) for case in self.cases) + "\n"


def score(suite: EvalSuite, case: EvalCase, output: RunOutput) -> dict[str, float]:
    scores: dict[str, float] = {}
    for evaluator in suite.evaluators:
        scores.update(evaluator(case, output))
    return scores


def is_plumbing(output: RunOutput) -> bool:
    if output.failure is not None:
        return output.failure.kind == "plumbing"
    return output.error is not None


def classify_error(output: RunOutput) -> RunError | None:
    """Prefer target classifications; classify untyped target exceptions conservatively."""
    if output.failure is not None:
        return output.failure
    if output.error:
        detail = output.error.lower()
        code = next(
            (
                code
                for code, needles in (
                    ("rate_limit", ("429", "rate limit", "ratelimit")),
                    ("timeout", ("timeout", "timed out")),
                    ("truncated_output", ("truncat", "incomplete", "max_output")),
                    ("transport", ("connection", "transport", "network")),
                )
                if any(needle in detail for needle in needles)
            ),
            "target_error",
        )
        return RunError(kind="plumbing", code=code, detail=output.error)
    if output.value is None and not output.text:
        return RunError(kind="plumbing", code="missing_output")
    return None


def aggregate(
    cases: list[CaseResult], *, zero_fill: frozenset[str] = frozenset()
) -> dict[str, float]:
    if not cases:
        return {}
    names = sorted(zero_fill | {name for case in cases for name in case.scores})
    return {
        name: mean(
            case.scores.get(name, 0.0) for case in cases if name in zero_fill or name in case.scores
        )
        for name in names
    }


def bootstrap_intervals(
    cases: list[CaseResult],
    *,
    samples: int = 2000,
    seed: int = 42,
    zero_fill: frozenset[str] = frozenset(),
) -> dict[str, tuple[float, float]]:
    """Percentile 95% CIs: resample cases, then repeats within each sampled case."""
    if samples < 1:
        raise ValueError("bootstrap samples must be positive")
    if not cases:
        return {}
    rng = random.Random(seed)
    intervals: dict[str, tuple[float, float]] = {}
    for name in sorted(zero_fill | {name for case in cases for name in case.scores}):
        clusters: dict[str, list[float]] = {}
        for case in sorted(cases, key=lambda case: (case.case_id, case.repeat)):
            if name in zero_fill or name in case.scores:
                clusters.setdefault(case.case_id, []).append(case.scores.get(name, 0.0))
        groups = list(clusters.values())
        draws: list[float] = []
        for _ in range(samples):
            sampled = [rng.choice(groups) for _ in groups]
            draws.append(mean(rng.choice(group) for group in sampled for _ in group))
        draws.sort()
        intervals[name] = (draws[int((samples - 1) * 0.025)], draws[int((samples - 1) * 0.975)])
    return intervals


def paired_difference_intervals(
    baseline: SuiteResult,
    candidate: SuiteResult,
) -> dict[str, tuple[float, float]]:
    """Bootstrap paired candidate-minus-baseline scores on the same case/repeat cohort."""
    required = baseline.minimum_score_metrics
    if required != candidate.minimum_score_metrics:
        raise ValueError("paired comparison requires identical minimum-score metrics")
    before = {(case.case_id, case.repeat): case for case in baseline.quality_cases if case.gated}
    after = {(case.case_id, case.repeat): case for case in candidate.quality_cases if case.gated}
    if before.keys() != after.keys():
        raise ValueError("paired comparison requires identical non-plumbing case/repeat cohorts")
    differences: list[CaseResult] = []
    for key in sorted(before):
        old, new = before[key], after[key]
        if old.scores.keys() - required != new.scores.keys() - required:
            raise ValueError("paired comparison requires identical metric applicability")
        differences.append(
            new.model_copy(
                update={
                    "scores": {
                        name: new.scores.get(name, 0.0) - old.scores.get(name, 0.0)
                        for name in required | new.scores.keys()
                    }
                }
            )
        )
    return bootstrap_intervals(
        differences, samples=candidate.bootstrap_samples, seed=candidate.bootstrap_seed
    )


async def run_suite(
    suite: EvalSuite,
    target: Target,
    *,
    concurrency: int = 3,
    retries: int = 2,
    backoff_s: float = 20.0,
    repeats: int = 1,
    on_result: Callable[[CaseResult], None] | None = None,
) -> SuiteResult:
    """Run every case through ``target`` (at most ``concurrency`` at a time) and score it.

    Plumbing failures retry with linear backoff and still fail the regression gate, but
    never enter quality denominators. Repeats are independent of retry attempts.
    Automatic quality-miss labels use only declared minimum-score metrics: informational
    metrics may be lower-is-better or have no per-answer acceptance policy.
    """
    if concurrency < 1 or repeats < 1 or retries < 0:
        raise ValueError("concurrency/repeats must be positive and retries nonnegative")
    semaphore = asyncio.Semaphore(concurrency)

    async def attempt(case: EvalCase) -> RunOutput:
        attempts = 0
        while True:
            attempts += 1
            started = time.perf_counter()
            try:
                output = await target(case)
            except Exception as error:
                output = RunOutput(error=f"{type(error).__name__}: {error}")
            output.duration_s = time.perf_counter() - started
            output.attempts = attempts
            output.failure = classify_error(output)
            if not is_plumbing(output) or attempts > retries:
                return output
            await asyncio.sleep(backoff_s * attempts)

    async def run_case(case: EvalCase, repeat: int) -> CaseResult:
        async with semaphore:
            output = await attempt(case)
        scores = {} if is_plumbing(output) else score(suite, case, output)
        if output.failure is None and any(
            scores.get(name, 0.0) < 1.0 for name in suite.thresholds.minimums
        ):
            output.failure = RunError(kind="wrong_answer", code="quality_miss")
        result = CaseResult(
            case_id=case.id,
            scores=scores,
            output=output,
            repeat=repeat,
            input=case.input,
            category=case.truth.category if case.truth else "clean",
            split=case.split,
            gated=suite.gate_case_ids is None or case.id in suite.gate_case_ids,
        )
        if on_result is not None:
            on_result(result)
        return result

    results = await asyncio.gather(
        *(
            run_case(case, repeat)
            for case in assign_splits(suite.cases)
            for repeat in range(1, repeats + 1)
        )
    )
    return SuiteResult(
        suite=suite.name,
        cases=list(results),
        minimum_score_metrics=frozenset(suite.thresholds.minimums),
    )
