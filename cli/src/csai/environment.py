"""Settings for the CLI: the process environment, a local ``.env``, then the azd environment.

Values already set win, so ``export`` and ``.env`` can override what azd provisioned.
"""

import json
import os
import shutil
import subprocess

from dotenv import load_dotenv


def azd_values() -> dict[str, str]:
    """The active azd environment's values, or nothing when azd isn't available."""
    azd = shutil.which("azd")
    if azd is None:
        return {}
    result = subprocess.run(
        [azd, "env", "get-values", "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    values: dict[str, object] = json.loads(result.stdout)
    return {key: str(value) for key, value in values.items()}


def load_environment(*, use_azd: bool = True) -> None:
    load_dotenv()
    if use_azd:
        for key, value in azd_values().items():
            os.environ.setdefault(key, value)
