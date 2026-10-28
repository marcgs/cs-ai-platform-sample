"""The case manifest is derived from the seed scenarios: an engineer's report plus ground truth.

``cases.jsonl`` is committed so that changes to the cases are reviewed like code. Regenerate
it after changing the seed data:

    uv run python -m rca_evals.manifest
"""

from importlib import resources
from pathlib import Path

from cs_platform.evals import EvalCase
from diagnostics_domain.dataset import DiagnosticsDataset, load_seed

CASES_FILE = "cases.jsonl"


def cases_from_seed(dataset: DiagnosticsDataset) -> list[EvalCase]:
    return [
        EvalCase(
            id=scenario.id,
            input=f"{scenario.machine_id}: {scenario.symptom}",
            expected={
                "machine_id": scenario.machine_id,
                "failure_mode": scenario.expected_failure_mode,
            },
        )
        for scenario in dataset.scenarios
    ]


def render(cases: list[EvalCase]) -> str:
    return "".join(case.model_dump_json() + "\n" for case in cases)


def main() -> None:
    path = Path(str(resources.files("rca_evals"))) / CASES_FILE
    path.write_text(render(cases_from_seed(load_seed())), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
