"""Explicit offline, preflight and approved-model commands; no implicit cloud calls."""

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from cs_platform.episode_io import load_episodes
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback_models import Review
from episode_analysis.classifier import (
    CachedClassifier,
    ClassifierConfig,
    Estimate,
    estimate,
    structured_classifier,
)
from episode_analysis.pipeline import analyze, prepare
from episode_analysis.report import write_report

if TYPE_CHECKING:
    from episode_analysis.pipeline import Prepared


def _model_config() -> ClassifierConfig:
    from cs_platform.settings import PlatformSettings

    settings = PlatformSettings.from_env()
    return ClassifierConfig(
        model=settings.model_deployment,
        project_endpoint=settings.foundry_project_endpoint,
        settings={},
    )


async def _run_model(
    prepared: Prepared, config: ClassifierConfig, cache: Path | None, output: Path
) -> bool:
    from azure.identity.aio import DefaultAzureCredential

    from cs_platform.factory import foundry_client
    from cs_platform.settings import PlatformSettings

    async with DefaultAzureCredential() as credential:
        client = foundry_client(PlatformSettings.from_env(), credential)
        classifier = CachedClassifier(structured_classifier(client, config), config, cache)
        report = await analyze(prepared, classifier)
    write_report(report, output)
    return not report.errors


def main(argv: list[str] | None = None) -> None:
    """Analyze JSONL locally, or explicitly estimate/approve Foundry classification."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    analysis = subparsers.add_parser("analyze", help="Offline unless --labeler foundry is explicit")
    analysis.add_argument("--episodes", type=Path, required=True)
    analysis.add_argument("--source", choices=["synthetic", "real"], required=True)
    analysis.add_argument("--reviews", type=Path)
    analysis.add_argument("--output", type=Path, default=Path("analysis-output/report"))
    analysis.add_argument("--labeler", choices=["offline", "foundry"], default="offline")
    analysis.add_argument("--cache", type=Path)
    analysis.add_argument(
        "--synthetic-seed-context", action="store_true", help="Join fictional seed metadata/history"
    )
    approval = analysis.add_mutually_exclusive_group()
    approval.add_argument("--estimate", type=Path, help="Dry-run only; write a model preflight")
    approval.add_argument(
        "--approved-estimate", type=Path, help="Explicit consent to matching traffic"
    )
    benchmark = subparsers.add_parser("benchmark", help="Separate offline answer-key evaluation")
    benchmark.add_argument("--report", type=Path, required=True)
    benchmark.add_argument("--answer-key", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--sample-size", type=int, default=100)
    benchmark.add_argument(
        "--allow-subset", action="store_true", help="Benchmark only the sampled report population"
    )
    sample = subparsers.add_parser("sample", help="Select a small pilot without an answer key")
    sample.add_argument("--episodes", type=Path, required=True)
    sample.add_argument("--reviews", type=Path, required=True)
    sample.add_argument("--source", choices=["synthetic", "real"], required=True)
    sample.add_argument("--misses", type=int, default=30)
    sample.add_argument("--controls", type=int, default=20)
    sample.add_argument("--seed", required=True, help="Predeclared deterministic selection seed")
    sample.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "benchmark":
        from diagnostics_domain.feedback_models import AnswerKey
        from episode_analysis.benchmark import evaluate
        from episode_analysis.models import Report

        result = evaluate(
            Report.model_validate_json(args.report.read_text()),
            AnswerKey.model_validate_json(args.answer_key.read_text()),
            sample_size=args.sample_size,
            allow_subset=args.allow_subset,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(result.model_dump_json(indent=2))
        return
    episodes = load_episodes(args.episodes, source=args.source)
    reviews = (
        [
            Review.model_validate_json(line)
            for line in args.reviews.read_text().splitlines()
            if line.strip()
        ]
        if args.reviews
        else []
    )
    if args.command == "sample":
        from episode_analysis.pilot import sample

        result = sample(
            episodes,
            reviews,
            misses=args.misses,
            controls=args.controls,
            seed=args.seed,
            output=args.output_dir,
        )
        print(result.model_dump_json(indent=2))
        return
    if args.synthetic_seed_context and any(episode.source != "synthetic" for episode in episodes):
        parser.error("--synthetic-seed-context is only valid for a synthetic population")
    prepared = prepare(episodes, reviews, load_seed() if args.synthetic_seed_context else None)
    if args.labeler == "offline":
        if args.cache:
            parser.error("--cache requires --labeler foundry; offline preparation does not label")
        if args.estimate or args.approved_estimate:
            parser.error("Preflight flags require --labeler foundry")
        report = asyncio.run(analyze(prepared))
        write_report(report, args.output)
        if report.errors:
            raise SystemExit(1)
        return
    if not args.estimate and not args.approved_estimate:
        parser.error("Foundry requires --estimate PATH first, then --approved-estimate PATH")
    config = _model_config()

    # Estimate reads only cache/input. The deliberately unusable callable cannot send traffic.
    async def unavailable(_: object):
        raise RuntimeError("Preflight cannot invoke a classifier")

    preflight = estimate(prepared.candidates, CachedClassifier(unavailable, config, args.cache))
    print(preflight.model_dump_json(indent=2))
    if args.estimate:
        args.estimate.parent.mkdir(parents=True, exist_ok=True)
        args.estimate.write_text(preflight.model_dump_json(indent=2), encoding="utf-8")
        return
    approved = Estimate.model_validate_json(args.approved_estimate.read_text())
    if (
        approved.fingerprint != preflight.fingerprint
        or approved.uncached_calls < preflight.uncached_calls
        or approved.estimated_input_tokens < preflight.estimated_input_tokens
        or approved.maximum_output_tokens < preflight.maximum_output_tokens
    ):
        parser.error("Preflight changed or budget increased; run --estimate again")
    if not asyncio.run(_run_model(prepared, config, args.cache, args.output)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
