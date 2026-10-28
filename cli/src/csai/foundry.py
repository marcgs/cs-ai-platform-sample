"""Publish an eval run to Foundry, scored by its built-in (model-judged) evaluators.

The code-based metrics stay the gate; Foundry adds judgment the code can't make (does the
answer follow the instructions, address the engineer's intent, read coherently) and keeps
every run, with per-case rows, next to the agent's traces in the portal.
"""

import time
from typing import TYPE_CHECKING, Any

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

if TYPE_CHECKING:
    from cs_platform.evals import EvalSuite, SuiteResult

BUILTIN_EVALUATORS = ("task_adherence", "intent_resolution", "coherence")
POLL_INTERVAL_S = 10.0
TIMEOUT_S = 900.0


class FoundryEvalError(RuntimeError):
    pass


def items(suite: EvalSuite, result: SuiteResult) -> list[dict[str, Any]]:
    cases = {case.id: case for case in suite.cases}
    return [
        {
            "item": {
                "case_id": case.case_id,
                "query": cases[case.case_id].input,
                "response": case.output.text or case.output.error or "",
                "ground_truth": ", ".join(
                    f"{k}={v}" for k, v in cases[case.case_id].expected.items()
                ),
                **{f"code_{name}": score for name, score in case.scores.items()},
            }
        }
        for case in result.cases
    ]


def publish(suite: EvalSuite, result: SuiteResult, *, endpoint: str, model: str, label: str) -> str:
    """Create a Foundry eval run for ``result``; returns the portal URL of the report."""
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint, credential) as project,
        project.get_openai_client() as client,
    ):
        evaluation = client.evals.create(
            name=f"{suite.name} agent",
            data_source_config={
                "type": "custom",
                "item_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "response": {"type": "string"}},
                    "required": ["query", "response"],
                },
                "include_sample_schema": False,
            },
            testing_criteria=[
                {
                    "type": "azure_ai_evaluator",
                    "name": name,
                    "evaluator_name": f"builtin.{name}",
                    "initialization_parameters": {"deployment_name": model},
                    "data_mapping": {"query": "{{item.query}}", "response": "{{item.response}}"},
                }
                for name in BUILTIN_EVALUATORS
            ],  # pyright: ignore[reportArgumentType] - Foundry-specific criterion type
        )
        run = client.evals.runs.create(
            eval_id=evaluation.id,
            name=label,
            data_source={
                "type": "jsonl",
                "source": {"type": "file_content", "content": items(suite, result)},
            },  # pyright: ignore[reportArgumentType]
        )
        deadline = time.monotonic() + TIMEOUT_S
        while run.status in {"queued", "in_progress"} and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_S)
            run = client.evals.runs.retrieve(run.id, eval_id=evaluation.id)
        if run.status != "completed":
            reason = run.error.message if run.error else "timed out"
            raise FoundryEvalError(f"Foundry eval run {run.id} {run.status}: {reason}")
        return run.report_url or run.id
