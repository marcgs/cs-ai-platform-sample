"""Prepare local feedback-case proposals; never commit, push or open a pull request."""

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from cs_platform.episode_io import load_episodes
from cs_platform.evals import EvalCase
from csai.case_proposal import CaseProposal, propose_cases
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback_models import Review
from episode_analysis.models import Report
from episode_analysis.pipeline import prepare, review_candidates
from rca_evals.feedback import load_feedback_cases

app = typer.Typer(no_args_is_help=True)
MANIFEST = Path("evals/rca/src/rca_evals/cases.jsonl")
FEEDBACK = MANIFEST.with_name("feedback_cases.jsonl")


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _reject_symlinks(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"Refusing symlink proposal path: {component}")


def _evidence(report: Report) -> str:
    lines = ["# Feedback proposal evidence", "", "Source: synthetic; human review required.", ""]
    clustered: set[str] = set()
    for cluster in sorted(report.clusters, key=lambda value: value.id):
        clustered.update(candidate.episode_id for candidate in cluster.eval_cases)
        lines.extend(
            [f"## Cluster {cluster.id}", "", f"{cluster.category}: {cluster.condition}", ""]
        )
    candidates = report.review_candidates or [
        candidate for cluster in report.clusters for candidate in cluster.eval_cases
    ]
    for candidate in sorted(candidates, key=lambda value: value.episode_id):
        if candidate.episode_id not in clustered:
            lines.extend(["Unclustered review evidence:", ""])
        lines.extend(
            [
                f"### Episode {candidate.episode_id}",
                "",
                f"Input: {candidate.input}",
                "",
                "Review summary:",
                "",
                "```json",
                candidate.review_summary.model_dump_json(indent=2),
                "```",
                "",
            ]
        )
        for review in sorted(candidate.source_reviews, key=lambda value: value.id):
            lines.extend(
                [
                    f"#### Review {review.id}",
                    "",
                    "```json",
                    review.model_dump_json(indent=2),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def _body(proposal: CaseProposal, evidence_path: Path) -> str:
    evidence = evidence_path.as_posix()
    lines = [
        "# Propose review-supported feedback eval cases",
        "",
        f"Report SHA-256: `{proposal.report_sha256}`",
        "",
        "Synthetic data only. Human review and merge are pending. No live acceptance claimed.",
        "This command did not commit, push or open a pull request.",
        "",
        f"Proposed cases: {len(proposal.cases)} (informational feedback cohort; not gated).",
        "",
        "## Candidate decisions",
        "",
        "| Cluster | Episode | Reviews | Decision | Consensus | Reason / existing case |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for decision in proposal.decisions:
        consensus = decision.consensus
        statistics = (
            f"{consensus.verdict or 'unresolved'}; "
            f"{consensus.independent_reviewers} independent; "
            f"agreement {consensus.agreement:.6f}; cause support {consensus.root_cause_support:.6f}"
            if consensus
            else "not admitted to consensus validation"
        )
        reviews = ", ".join(
            f"[{review_id}]({evidence}#review-{review_id.lower()})"
            for review_id in decision.review_ids
        )
        reason = decision.reason.replace("|", "\\|").replace("\n", " ")
        if decision.case_id:
            path = FEEDBACK if decision.case_id.startswith("FB-") else MANIFEST
            reason += f"; [{decision.case_id}]({path.as_posix()})"
        cluster = (
            f"[{decision.cluster_key}]({evidence}#cluster-{decision.cluster_key})"
            if decision.cluster_key
            else "unclustered"
        )
        lines.append(
            f"| {cluster} "
            f"| [{decision.episode_id}]({evidence}#episode-{decision.episode_id.lower()}) "
            f"| {reviews} | {decision.status} | {statistics} | {reason} |"
        )
    for title, status in (("Expert review", "expert"), ("Waiting for reviews", "wait")):
        lines.extend(["", f"## {title}", ""])
        lines.extend(
            f"- `{decision.episode_id}`: {decision.reason}"
            for decision in proposal.decisions
            if decision.status == status
        )
        if not any(decision.status == status for decision in proposal.decisions):
            lines.append("None.")
    lines.extend(["", "## K4: non-replayable candidates", ""])
    lines.extend(
        f"- `{decision.episode_id}`: {decision.reason}"
        for decision in proposal.decisions
        if decision.k4
    )
    if not any(decision.k4 for decision in proposal.decisions):
        lines.append("None.")
    lines.extend(["", "## Metric applicability and limitations", ""])
    lines.extend(f"- {limitation}" for limitation in proposal.limitations)
    lines.extend(
        [
            "- Review IDs and weighted summaries are checked for consistency, not authenticated.",
            "- No synthetic answer key is used for admission.",
            "- Review the diff and source evidence before committing or opening a PR.",
            "",
        ]
    )
    return "\n".join(lines)


def write_proposal(report: Report, repository: Path) -> tuple[CaseProposal, str, Path]:
    """Write deterministic files on a new local branch, safely allowing identical reruns."""
    repository = repository.absolute()
    _reject_symlinks(repository)
    repository = repository.resolve()
    if Path(_git(repository, "rev-parse", "--show-toplevel")).resolve() != repository:
        raise ValueError("--repository must name the repository root")
    manifest_path = repository / MANIFEST
    _reject_symlinks(manifest_path)
    original = tuple(
        EvalCase.model_validate_json(line)
        for line in manifest_path.read_text("utf-8").splitlines()
        if line.strip()
    )
    feedback_path = repository / FEEDBACK
    _reject_symlinks(feedback_path)
    previous = load_feedback_cases(feedback_path, existing=original)
    proposal = propose_cases(report, (*original, *previous))
    existing_by_id = {case.id: case for case in (*original, *previous)}
    for case in proposal.cases:
        existing = existing_by_id.get(case.id)
        if existing is not None and existing != case:
            raise ValueError(f"Conflicting existing case ID: {case.id}")
    combined = {case.id: case for case in previous}
    combined.update({case.id: case for case in proposal.cases})
    rendered = "".join(combined[case_id].model_dump_json() + "\n" for case_id in sorted(combined))
    branch = f"feedback/cases-{proposal.report_sha256[:12]}"
    relative = Path("docs/iteration-4/proposals") / proposal.report_sha256[:12]
    artifacts = repository / relative
    output = {
        artifacts / "proposal.json": proposal.model_dump_json(indent=2) + "\n",
        artifacts / "report.json": report.model_dump_json(indent=2) + "\n",
        artifacts / "evidence.md": _evidence(report),
        artifacts / "pr-body.md": _body(proposal, relative / "evidence.md"),
    }
    for path, content in output.items():
        _reject_symlinks(path)
        if path.exists() and path.read_text("utf-8") != content:
            raise ValueError(f"Refusing to overwrite changed proposal artifact: {path.name}")
    current = _git(repository, "branch", "--show-current")
    if current != branch:
        exists = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ],
            check=False,
        )
        if exists.returncode == 0:
            raise ValueError(f"Proposal branch already exists; switch to {branch} before rerunning")
        _git(repository, "switch", "-c", branch)
    artifacts.mkdir(parents=True, exist_ok=True)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(rendered, encoding="utf-8")
    for path, content in output.items():
        path.write_text(content, encoding="utf-8")
    return proposal, branch, artifacts / "pr-body.md"


@app.command("propose")
def propose(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    repository: Annotated[
        Path, typer.Option(help="Repository root for the local proposal branch and files.")
    ] = Path(),
    episodes: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, help="Full fresh-cohort episodes.")
    ] = None,
    reviews: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, help="Full fresh-cohort reviews.")
    ] = None,
) -> None:
    """Propose consensus/replay-backed cases, with optional cluster provenance."""
    try:
        source = Report.model_validate_json(report.read_text("utf-8"))
        if (episodes is None) != (reviews is None):
            raise ValueError("--episodes and --reviews must be supplied together")
        if episodes is not None and reviews is not None:
            cohort = prepare(
                load_episodes(episodes, source="synthetic"),
                [
                    Review.model_validate_json(line)
                    for line in reviews.read_text("utf-8").splitlines()
                    if line.strip()
                ],
                load_seed(),
            )
            if (
                source.source != cohort.source
                or sorted(source.episode_ids) != cohort.episode_ids
                or source.episode_count != cohort.episode_count
                or source.reviewed_count != cohort.reviewed_count
                or source.uncertain_count != cohort.uncertain_count
                or source.reviewer_agreement != cohort.agreement
            ):
                raise ValueError("Fresh-cohort evidence conflicts with the report")
            attached = review_candidates(cohort)
            by_episode = {candidate.episode_id: candidate for candidate in attached}
            retained = [
                *source.review_candidates,
                *(candidate for cluster in source.clusters for candidate in cluster.eval_cases),
            ]
            for candidate in retained:
                fresh = by_episode.get(candidate.episode_id)
                if fresh is None or fresh.model_dump(exclude={"expected_category"}) != (
                    candidate.model_dump(exclude={"expected_category"})
                ):
                    raise ValueError("Fresh-cohort evidence conflicts with retained candidates")
            enriched = {item.episode.id: item for item in cohort.reviewed_episodes}
            for item in source.unclassified:
                fresh_item = enriched.get(item.episode.id)
                if fresh_item is None or (
                    fresh_item.episode != item.episode
                    or fresh_item.review != item.review
                    or fresh_item.expected_failure_mode != item.expected_failure_mode
                    or fresh_item.expected_mode_basis != item.expected_mode_basis
                ):
                    raise ValueError("Fresh-cohort evidence conflicts with retained unclassified")
            source = source.model_copy(update={"review_candidates": attached})
        result, branch, body = write_proposal(source, repository)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Branch: {branch}")
    typer.echo(f"Cases: {len(result.cases)}; decisions: {len(result.decisions)}")
    typer.echo(f"PR body: {body}")
    typer.echo("Human review pending. Nothing committed, pushed or opened.")
