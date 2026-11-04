"""The RCA agent's test cases: an engineer's report plus the known answer.

Each case is one line of ``cases.jsonl``, generated from the seed scenarios by
``rca_evals.manifest``. The answer key (``expected`` and ``truth``) is what an evaluation
compares the agent's diagnosis with; it is never inferred from an agent's answer.
"""

import hashlib
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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

CASES_FILE = "cases.jsonl"


class EvalTruth(BaseModel):
    """Causal ground truth supplied by the dataset."""

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
    expected: dict[str, str] = Field(description="The machine and failure mode to find.")
    truth: EvalTruth | None = None
    split: Split | None = None


def cases_path() -> Path:
    return Path(str(resources.files("rca_evals"))) / CASES_FILE


def load_cases(path: Path | None = None) -> tuple[EvalCase, ...]:
    """The committed cases, in manifest order."""
    text = (path or cases_path()).read_text("utf-8")
    return tuple(EvalCase.model_validate_json(line) for line in text.splitlines() if line.strip())


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
