"""Evaluation harness: run an agent over a versioned case manifest, score it, and gate on it.

An agent's suite is data plus code: ``cases.jsonl`` (one :class:`EvalCase` per line),
``thresholds.yaml`` (minimum mean per metric) and evaluators, plain functions that score one
case's output. A *target* runs one case against some deployment of the agent (in-process,
hosted, ...), so the same suite gates local changes and deployed versions alike.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from statistics import mean
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    input: str = Field(description="The message sent to the agent.")
    expected: dict[str, str] = Field(description="Ground truth, interpreted by the evaluators.")


class RunOutput(BaseModel):
    """What a target observed when running one case."""

    text: str | None = None
    value: Any = Field(default=None, description="Parsed structured output, if any.")
    tool_calls: list[str] = Field(default_factory=list[str])
    error: str | None = None
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

    @classmethod
    def from_files(
        cls, name: str, cases: Path, thresholds: Path, evaluators: tuple[Evaluator, ...]
    ) -> EvalSuite:
        lines = cases.read_text(encoding="utf-8").splitlines()
        return cls(
            name=name,
            cases=tuple(EvalCase.model_validate_json(line) for line in lines if line.strip()),
            thresholds=Thresholds.model_validate(yaml.safe_load(thresholds.read_text("utf-8"))),
            evaluators=evaluators,
        )


class CaseResult(BaseModel):
    case_id: str
    scores: dict[str, float]
    output: RunOutput


class SuiteResult(BaseModel):
    suite: str
    cases: list[CaseResult]

    @property
    def metrics(self) -> dict[str, float]:
        """Mean score per metric; a case without a score for a metric counts as 0."""
        names = sorted({name for case in self.cases for name in case.scores})
        if not self.cases:
            return dict.fromkeys(names, 0.0)
        return {name: mean(case.scores.get(name, 0.0) for case in self.cases) for name in names}

    @property
    def errored(self) -> list[str]:
        """Cases the target couldn't run, even after retries."""
        return [case.case_id for case in self.cases if case.output.error]

    def failures(self, thresholds: Thresholds) -> list[str]:
        """Why the gate fails: errored cases first, then threshold violations."""
        metrics = self.metrics
        failures: list[str] = []
        if self.errored:
            failures.append(f"{len(self.errored)} case(s) errored: {', '.join(self.errored)}")
        failures.extend(
            f"{name}: {metrics.get(name, 0.0):.2f} < {minimum:.2f}"
            for name, minimum in thresholds.minimums.items()
            if metrics.get(name, 0.0) < minimum
        )
        return failures

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(case.model_dump(mode="json")) for case in self.cases) + "\n"


def score(suite: EvalSuite, case: EvalCase, output: RunOutput) -> dict[str, float]:
    scores: dict[str, float] = {}
    for evaluator in suite.evaluators:
        scores.update(evaluator(case, output))
    return scores


async def run_suite(
    suite: EvalSuite,
    target: Target,
    *,
    concurrency: int = 3,
    retries: int = 2,
    backoff_s: float = 20.0,
    on_result: Callable[[CaseResult], None] | None = None,
) -> SuiteResult:
    """Run every case through ``target`` (at most ``concurrency`` at a time) and score it.

    A case whose target raises (rate limits, timeouts) is retried with linear backoff. If it
    still fails, the error is recorded and the case is scored like any other output, so one
    broken case lowers the metrics and is reported instead of aborting the run.
    """
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
            if output.error is None or attempts > retries:
                return output
            await asyncio.sleep(backoff_s * attempts)

    async def run_case(case: EvalCase) -> CaseResult:
        async with semaphore:
            output = await attempt(case)
        result = CaseResult(case_id=case.id, scores=score(suite, case, output), output=output)
        if on_result is not None:
            on_result(result)
        return result

    results = await asyncio.gather(*(run_case(case) for case in suite.cases))
    return SuiteResult(suite=suite.name, cases=list(results))
