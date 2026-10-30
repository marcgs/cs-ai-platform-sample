import json
from typing import TYPE_CHECKING

import pytest

from cs_platform.episode_io import export_episodes, load_episodes
from cs_platform.episodes import Episode

if TYPE_CHECKING:
    from pathlib import Path


def test_real_episode_roundtrip_and_legacy_label(tmp_path: Path) -> None:
    episode = Episode(agent="test", agent_version="1", input="M-0001: fictional incident")
    path = tmp_path / "real" / "episodes.jsonl"
    export_episodes([episode], path)
    assert load_episodes(path) == [episode]
    assert json.loads(path.read_text("utf-8"))["source"] == "real"
    with pytest.raises(FileExistsError):
        export_episodes([episode], path)
    legacy = episode.model_dump(mode="json", exclude={"source"})
    assert Episode.model_validate(legacy).source == "real"
    path.write_text(json.dumps(legacy) + "\n", "utf-8")
    with pytest.raises(ValueError, match="explicit real"):
        load_episodes(path)


def test_export_and_import_reject_mixed_or_relabelled_populations(tmp_path: Path) -> None:
    real = Episode(agent="test", agent_version="1", input="M-0001")
    synthetic = Episode(agent="test", agent_version="1", input="M-0002", source="synthetic")
    path = tmp_path / "episodes.jsonl"
    with pytest.raises(ValueError, match="only real"):
        export_episodes([real, synthetic], path)
    assert not path.exists()
    export_episodes([synthetic], path, source="synthetic")
    assert load_episodes(path, source="synthetic") == [synthetic]
    with pytest.raises(ValueError, match="explicit real"):
        load_episodes(path)
    path.write_text(real.model_dump_json() + "\n" + synthetic.model_dump_json(), "utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_episodes(path)
