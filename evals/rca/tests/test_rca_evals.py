import json
from collections import Counter
from pathlib import Path

from diagnostics_domain.dataset import load_seed
from rca_evals import load_cases
from rca_evals.manifest import cases_from_seed, render


def test_committed_manifest_matches_the_seed_scenarios() -> None:
    cases = load_cases()
    assert render(list(cases)) == render(cases_from_seed(load_seed(), previous=cases))
    assert len(cases) == len(load_seed().scenarios)


def test_every_case_has_an_answer_key_and_a_split() -> None:
    cases = load_cases()
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.truth is not None and case.split is not None for case in cases)
    assert Counter(case.split for case in cases)["test"] > 0


def test_evaluation_queries_are_case_inputs() -> None:
    queries = Path(__file__).parents[1] / "queries.jsonl"
    rows = [json.loads(line) for line in queries.read_text(encoding="utf-8").splitlines()]
    inputs = {case.input for case in load_cases()}
    assert rows
    assert all(row["query"] in inputs for row in rows)


def test_manifest_preserves_persisted_machine_splits_on_extension() -> None:
    dataset = load_seed()
    before = cases_from_seed(dataset)
    added = dataset.scenarios[0].model_copy(update={"id": "SC-999", "machine_id": "M-9999"})
    after = cases_from_seed(
        dataset.model_copy(update={"scenarios": (*dataset.scenarios, added)}),
        previous=before,
    )
    assert {case.id: case.split for case in before} == {
        case.id: case.split for case in after if case.id != added.id
    }
    for category in {case.truth.category for case in before if case.truth}:
        splits = {case.split for case in before if case.truth and case.truth.category == category}
        assert splits == {"train", "test"}
