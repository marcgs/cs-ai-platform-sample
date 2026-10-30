import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_installed_wheel_contains_and_loads_skill(tmp_path: Path) -> None:
    package = Path(__file__).resolve().parents[1]
    distributions = tmp_path / "dist"
    subprocess.run(
        [
            "uv",
            "build",
            "--offline",
            "--no-build-isolation",
            "--sdist",
            "--out-dir",
            str(distributions),
            str(package),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    [sdist] = distributions.glob("*.tar.gz")
    subprocess.run(
        [
            "uv",
            "build",
            "--offline",
            "--no-build-isolation",
            "--wheel",
            "--out-dir",
            str(distributions),
            str(sdist),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    [wheel] = distributions.glob("*.whl")
    relative = "rca_agent/skills/rca-investigation/SKILL.md"
    with ZipFile(wheel) as archive:
        assert (
            archive.read(relative) == (package / "skills/rca-investigation/SKILL.md").read_bytes()
        )
    installed = tmp_path / "installed"
    subprocess.run(
        ["uv", "pip", "install", "--offline", "--no-deps", "--target", str(installed), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
from importlib import resources
from pathlib import Path
import mcp, tenacity, rca_agent.main
import rca_agent
from rca_agent.agent import load_rca_spec
from rca_agent.skill import load_investigation_skill
assert Path(rca_agent.__file__).is_relative_to(Path.cwd() / "installed")
assert resources.files("rca_agent").joinpath("skills/rca-investigation/SKILL.md").is_file()
skill = load_investigation_skill()
assert skill.metadata.name == "rca-investigation"
assert skill.metadata.version == "1.0.0"
assert load_rca_spec().instructions.count(skill.body) == 1
assert load_investigation_skill().body
""",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed)},
        check=True,
        capture_output=True,
        text=True,
    )
