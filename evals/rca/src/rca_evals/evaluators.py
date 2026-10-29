"""Code-based evaluators for RCA reports.

Each evaluator scores one case's output from 0 to 1 per metric:

- ``schema_valid``: a parseable report for the right machine, 1-3 hypotheses ranked 1..n,
  each with at least one evidence item.
- ``hit_at_1`` / ``hit_at_3``: the expected failure mode is ranked first / in the top 3.
- ``evidence_grounded``: share of cited refs that resolve to a real record of this machine
  (or to shared reference data: error codes, historical cases).
- ``tool_coverage``: share of the diagnostic tools the agent called; an investigation
  without error events, telemetry or the logbook is guesswork, however plausible it reads.
- ``used_knowledge``: whether the report cites a historical case. Informational, no gate.
- ``knowledge_search_called``: whether historical search ran, independently of citations.
  Informational, no gate; direct-MCP runs have no search tool.
"""

from functools import cache
from typing import TYPE_CHECKING

from diagnostics_domain.dataset import DiagnosticsDataset, load_seed
from diagnostics_mcp.tools import TOOL_NAMES
from rca_agent.report import RcaReport

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cs_platform.evals import EvalCase, RunOutput


@cache
def _dataset() -> DiagnosticsDataset:
    return load_seed()


def _report(output: RunOutput) -> RcaReport | None:
    return output.value if isinstance(output.value, RcaReport) else None


def _schema_valid(case: EvalCase, report: RcaReport) -> bool:
    ranks = [h.rank for h in report.hypotheses]
    return (
        report.machine_id == case.expected["machine_id"]
        and 1 <= len(report.hypotheses) <= 3
        and sorted(ranks) == list(range(1, len(ranks) + 1))
        and all(h.evidence for h in report.hypotheses)
    )


def outcome(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
    report = _report(output)
    if report is None:
        return {"schema_valid": 0.0, "hit_at_1": 0.0, "hit_at_3": 0.0, "used_knowledge": 0.0}
    ranked = [h.failure_mode_id for h in sorted(report.hypotheses, key=lambda h: h.rank)]
    expected = case.expected["failure_mode"]
    refs = [e.ref for h in report.hypotheses for e in h.evidence]
    return {
        "schema_valid": float(_schema_valid(case, report)),
        "hit_at_1": float(ranked[:1] == [expected]),
        "hit_at_3": float(expected in ranked[:3]),
        "used_knowledge": float(any(ref.startswith("HC-") for ref in refs)),
    }


def ref_exists(ref: str, machine_id: str, dataset: DiagnosticsDataset) -> bool:
    """Whether a cited ref names a real record that belongs to this machine's investigation."""
    prefix, _, rest = ref.partition(":")
    if prefix == "TS":
        machine, _, signal = rest.partition(":")
        return machine == machine_id and any(s.name == signal for s in dataset.signals)
    if ref.startswith("EV-"):
        return any(e.id == ref and e.machine_id == machine_id for e in dataset.error_events)
    if ref.startswith("LB-"):
        return any(e.id == ref and e.machine_id == machine_id for e in dataset.logbook)
    if ref.startswith("EC-"):
        return any(c.code == ref for c in dataset.error_codes)
    if ref.startswith("HC-"):
        return any(c.id == ref for c in dataset.historical_cases)
    return False


def evidence_grounded(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
    report = _report(output)
    refs = [e.ref for h in report.hypotheses for e in h.evidence] if report else []
    if not refs:
        return {"evidence_grounded": 0.0}
    machine_id = case.expected["machine_id"]
    grounded = sum(ref_exists(ref, machine_id, _dataset()) for ref in refs)
    return {"evidence_grounded": grounded / len(refs)}


def tool_coverage(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
    # Toolboxes prefix tool names with the server label (e.g. diagnostics___get_logbook).
    called = {name.rpartition("___")[2] for name in output.tool_calls}
    return {"tool_coverage": len(called & set(TOOL_NAMES)) / len(TOOL_NAMES)}


def knowledge_search(case: EvalCase, output: RunOutput) -> Mapping[str, float]:
    """Track search calls separately: irrelevant results need not become citations."""
    called = {name.rpartition("___")[2] for name in output.tool_calls}
    return {"knowledge_search_called": float("azure_ai_search" in called)}
