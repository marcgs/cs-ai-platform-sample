"""The case manifest is derived from the seed scenarios: an engineer's report plus ground truth.

``cases.jsonl`` is committed so that changes to the cases are reviewed like code. Regenerate
it after changing the seed data:

    uv run python -m rca_evals.manifest
"""

from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from cs_platform.evals import EvalCase, EvalTruth, assign_splits
from diagnostics_domain.dataset import DiagnosticsDataset, load_seed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cs_platform.evals import Split
CASES_FILE = "cases.jsonl"


def cases_from_seed(
    dataset: DiagnosticsDataset, previous: Sequence[EvalCase] = ()
) -> list[EvalCase]:
    previous_splits: dict[str, Split | None] = {
        case.expected["machine_id"]: case.split for case in assign_splits(tuple(previous))
    }
    return list(
        assign_splits(
            tuple(
                EvalCase(
                    id=scenario.id,
                    input=scenario.incident_input(),
                    expected={
                        "machine_id": scenario.machine_id,
                        "failure_mode": scenario.expected_failure_mode,
                    },
                    truth=EvalTruth(
                        category=scenario.category,
                        decisive_refs=scenario.decisive_refs,
                        acceptable_failure_modes=scenario.acceptable_failure_modes,
                        ruled_out_failure_modes=scenario.ruled_out_failure_modes,
                        confirming_checks=scenario.confirming_checks,
                        injection_markers=scenario.injection_markers,
                    ),
                    split=previous_splits.get(scenario.machine_id),
                )
                for scenario in dataset.scenarios
            )
        )
    )


def render(cases: list[EvalCase]) -> str:
    return "".join(case.model_dump_json() + "\n" for case in cases)


def main() -> None:
    path = Path(str(resources.files("rca_evals"))) / CASES_FILE
    previous = (
        tuple(
            EvalCase.model_validate_json(line)
            for line in path.read_text("utf-8").splitlines()
            if line.strip()
        )
        if path.exists()
        else ()
    )
    path.write_text(render(cases_from_seed(load_seed(), previous=previous)), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
