"""Explicit, source-separated episode interchange; never connects to an episode store."""

from typing import TYPE_CHECKING, Literal

from cs_platform.episodes import Episode

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

type EpisodeSource = Literal["real", "synthetic"]


def export_episodes(
    episodes: Iterable[Episode], path: Path, *, source: EpisodeSource = "real"
) -> None:
    """Create JSONL exclusively for one source, refusing mixed data and existing files.

    Validate the whole collection before opening the destination. Legacy real episodes
    acquire an explicit label on export. No store is read or changed by this helper.
    """
    records = list(episodes)
    if any(episode.source != source for episode in records):
        raise ValueError(f"Expected only {source} episodes")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for episode in records:
            stream.write(episode.model_dump_json() + "\n")


def load_episodes(path: Path, *, source: EpisodeSource = "real") -> list[Episode]:
    """Read one explicitly labeled population; reject missing, mixed or wrong labels."""
    episodes: list[Episode] = []
    for line_number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        episode = Episode.model_validate_json(line)
        if "source" not in episode.model_fields_set or episode.source != source:
            raise ValueError(f"Expected explicit {source} source on line {line_number}")
        episodes.append(episode)
    return episodes
