"""Generate source-separated, synthetic episode/review populations without live calls."""

import argparse
from datetime import timedelta
from pathlib import Path
from random import Random
from uuid import NAMESPACE_OID, uuid5

from pydantic import BaseModel, ConfigDict

from cs_platform.episode_io import export_episodes, load_episodes
from cs_platform.episodes import Episode, Usage, Verdict
from diagnostics_domain.dataset import load_seed
from diagnostics_domain.feedback_models import AnswerKey, EpisodeTruth, Review
from diagnostics_domain.feedback_patterns import planted_patterns
from diagnostics_domain.feedback_reviews import make_reviews
from diagnostics_domain.feedback_transcripts import choose_scenario, make_transcript


class FeedbackDataset(BaseModel):
    """In-memory generation result; the answer key is written separately from inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episodes: list[Episode]
    reviews: list[Review]
    answer_key: AnswerKey


def generate_feedback(*, count: int = 2_000, seed: int = 42) -> FeedbackDataset:
    """Generate deterministic seed-backed examples with five failure/control pairs.

    Every ten episodes contain one miss of each kind and five matched correct controls.
    Separate per-episode random streams make prefixes stable when count increases.
    Neither the answer key nor a pattern ID is put into an episode or a review.
    """
    if count < 1:
        raise ValueError("count must be positive")
    dataset = load_seed()
    patterns = planted_patterns()
    episodes: list[Episode] = []
    reviews: list[Review] = []
    truths: list[EpisodeTruth] = []
    for index in range(count):
        rng = Random(f"feedback:{seed}:episode:{index}")
        context = index % 5
        failed = index % 10 < 5
        scenario = choose_scenario(dataset, context, rng)
        machine = dataset.machine(scenario.machine_id)
        created_at = dataset.reference_time + timedelta(days=1, minutes=index * 3)
        calls, output, expected, reported = make_transcript(
            dataset,
            scenario,
            context=context,
            failed=failed,
            started_at=created_at,
            rng=rng,
        )
        episode = Episode(
            id=uuid5(NAMESPACE_OID, f"synthetic-feedback:{seed}:{index}").hex,
            source="synthetic",
            agent="rca",
            agent_version="synthetic-1",
            created_at=created_at,
            completed_at=created_at + timedelta(seconds=len(calls) + 2),
            status="succeeded",
            input=f"{machine.id}: {scenario.symptom}",
            tool_calls=calls,
            output=output,
            usage=Usage(
                input_tokens=rng.randint(2_000, 6_000), output_tokens=rng.randint(300, 900)
            ),
        )
        history = [
            item.downtime_hours
            for item in dataset.historical_cases
            if item.confirmed_failure_mode == scenario.expected_failure_mode
        ]
        truth = EpisodeTruth(
            episode_id=episode.id,
            pattern_id=patterns[context].id if failed else None,
            expected_failure_mode=expected,
            actual_failure_mode=reported,
            verdict=Verdict.INCORRECT if failed else Verdict.CORRECT,
            machine_id=machine.id,
            platform=machine.platform,
            software_release=machine.software_release,
            downtime_hours=round(sum(history) / len(history), 2) if history else 0,
        )
        if failed:
            patterns[context].episode_ids.append(episode.id)
        episode_reviews = make_reviews(
            episode,
            truth,
            context=context,
            index=index,
            rng=Random(f"feedback:{seed}:reviews:{index}"),
        )
        episode.feedback = episode_reviews[0].feedback
        episodes.append(episode)
        reviews.extend(episode_reviews)
        truths.append(truth)
    return FeedbackDataset(
        episodes=episodes,
        reviews=reviews,
        answer_key=AnswerKey(seed=seed, patterns=patterns, episodes=truths),
    )


def _validate_population(population: FeedbackDataset) -> None:
    episode_ids = {episode.id for episode in population.episodes}
    truths = population.answer_key.episodes
    patterns = population.answer_key.patterns
    pattern_ids = {pattern.id for pattern in patterns}
    if (
        len(episode_ids) != len(population.episodes)
        or len(truths) != len(episode_ids)
        or any(episode.source != "synthetic" for episode in population.episodes)
        or any(
            review.source != "synthetic" or review.episode_id not in episode_ids
            for review in population.reviews
        )
        or {truth.episode_id for truth in truths} != episode_ids
        or len(pattern_ids) != len(patterns)
        or any(
            truth.pattern_id is not None and truth.pattern_id not in pattern_ids for truth in truths
        )
        or any(
            len(pattern.episode_ids) != len(set(pattern.episode_ids))
            or set(pattern.episode_ids)
            != {truth.episode_id for truth in truths if truth.pattern_id == pattern.id}
            for pattern in patterns
        )
    ):
        raise ValueError("Expected a complete, source-separated synthetic population")


def write_feedback(population: FeedbackDataset, output_dir: Path) -> None:
    """Write three new files in an empty directory, refusing source or reference mixing."""
    _validate_population(population)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("Output directory must be empty; never combine populations")
    output_dir.mkdir(parents=True, exist_ok=True)
    export_episodes(population.episodes, output_dir / "episodes.jsonl", source="synthetic")
    with (output_dir / "reviews.jsonl").open("x", encoding="utf-8") as stream:
        for review in population.reviews:
            stream.write(review.model_dump_json() + "\n")
    with (output_dir / "answer_key.json").open("x", encoding="utf-8") as stream:
        stream.write(population.answer_key.model_dump_json(indent=2) + "\n")


def load_feedback(output_dir: Path) -> FeedbackDataset:
    """Read an explicit synthetic bundle without accessing any episode store."""
    episodes = load_episodes(output_dir / "episodes.jsonl", source="synthetic")
    reviews = [
        Review.model_validate_json(line)
        for line in (output_dir / "reviews.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    answer_key = AnswerKey.model_validate_json((output_dir / "answer_key.json").read_text("utf-8"))
    if "source" not in answer_key.model_fields_set:
        raise ValueError("Expected an explicitly synthetic answer key")
    population = FeedbackDataset(episodes=episodes, reviews=reviews, answer_key=answer_key)
    _validate_population(population)
    return population


def main(argv: list[str] | None = None) -> None:
    """Generate an offline population; defaults to a dedicated, gitignored directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=Path("generated/synthetic-feedback"))
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be positive")
    population = generate_feedback(count=args.count, seed=args.seed)
    write_feedback(population, args.output_dir)
    print(
        f"Wrote {len(population.episodes)} synthetic episodes "
        f"and {len(population.reviews)} reviews."
    )


if __name__ == "__main__":
    main()
