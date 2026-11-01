"""Load reviewed feedback cases additively, without changing regression gates."""

import hashlib
import re
from typing import TYPE_CHECKING

from cs_platform.evals import EvalCase, assign_splits

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def case_identity(case: EvalCase) -> tuple[str, str, str]:
    """The incident identity shared by seed and reviewed feedback manifests."""
    machine = case.expected.get("machine_id", "")
    mode = case.expected.get("failure_mode", "")
    if (
        not machine.strip()
        or not mode.strip()
        or machine != machine.strip()
        or mode != mode.strip()
    ):
        raise ValueError(f"{case.id}: expected machine_id and failure_mode")
    return (
        machine,
        mode,
        case.truth.category if case.truth else "clean",
    )


def load_feedback_cases(path: Path, *, existing: Sequence[EvalCase] = ()) -> tuple[EvalCase, ...]:
    """Read an optional reviewed file, rejecting duplicates and train/test leakage."""
    if not path.exists():
        return ()
    cases = tuple(
        EvalCase.model_validate_json(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    )
    ids = {case.id for case in existing}
    identities = {case_identity(case) for case in existing}
    for case in cases:
        provenance = case.provenance
        if (
            case.cohort != "feedback"
            or provenance is None
            or case.truth is None
            or case.split is None
            or not case.id.startswith("FB-")
            or not provenance.review_ids
            or any(not review_id.strip() for review_id in provenance.review_ids)
            or len(set(provenance.review_ids)) != len(provenance.review_ids)
            or len(set(provenance.supporting_review_ids)) < 2
            or len(set(provenance.supporting_review_ids)) != len(provenance.supporting_review_ids)
            or not set(provenance.supporting_review_ids) <= set(provenance.review_ids)
            or not provenance.episode_id.strip()
            or provenance.verdict == "correct"
            or not re.fullmatch(r"[a-z]+(?:_[a-z]+)*", provenance.analysis_category)
            or not re.fullmatch(r"[a-z]+(?:_[a-z]+)*", provenance.condition)
            or provenance.cluster_key
            != hashlib.sha256(
                f"{provenance.analysis_category}:{provenance.condition}".encode()
            ).hexdigest()[:16]
            or not provenance.tool_fingerprints
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                for fingerprint in provenance.tool_fingerprints
            )
            or any(
                (
                    case.truth.decisive_refs,
                    case.truth.acceptable_failure_modes,
                    case.truth.ruled_out_failure_modes,
                    case.truth.confirming_checks,
                    case.truth.injection_markers,
                )
            )
        ):
            raise ValueError(f"{case.id}: expected a review-supported feedback case")
        identity = case_identity(case)
        if case.id in ids or identity in identities:
            raise ValueError(f"{case.id}: duplicate case identity")
        ids.add(case.id)
        identities.add(identity)
    assign_splits((*existing, *cases))
    return cases
