#!/bin/sh
# Prepares a function app under services/ for deployment without a remote build.
#
#   scripts/package_function.sh <package> <workspace dependency>...
#
# The apps depend on workspace packages that aren't published, so Oryx (remote build) can't
# install them. Instead, install the locked third-party versions (exported from the local
# uv.lock) and wheels of the workspace packages as Linux x86_64 wheels for Python 3.14 into
# .python_packages, where the Functions host loads them from. Run from the service directory.
set -eu

package=$1
shift
root=$(cd "$(dirname "$0")/.." && pwd)
service=$(pwd)
wheels="$service/.python_packages/wheels"
target="$service/.python_packages/lib/site-packages"
requirements="$service/.python_packages/requirements.txt"

rm -rf "$service/.python_packages"
mkdir -p "$wheels"
uv export --quiet --frozen --package "$package" --no-dev --no-emit-workspace --no-header \
  --directory "$root" -o "$requirements"
for workspace_package in "$package" "$@"; do
  uv build --quiet --wheel --package "$workspace_package" --out-dir "$wheels" --directory "$root"
done
install() {
  uv pip install --quiet --target "$target" --python-version 3.14 \
    --python-platform x86_64-manylinux_2_28 --only-binary :all: "$@"
}
install --require-hashes -r "$requirements"
install --no-deps "$wheels"/*.whl
# Inspect only the Linux payload, not the editable workspace. Native extensions
# cannot be imported on a macOS packaging host.
uv run --frozen --no-sync --directory "$root" python - "$root" "$target" <<'PY'
import re
import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path

root, target = sys.argv[1:]
sources = tomllib.loads(Path(root, "pyproject.toml").read_text())["tool"]["uv"]["sources"]
workspace = {name for name, source in sources.items() if source.get("workspace")}
installed = {dist.metadata["Name"]: dist for dist in distributions(path=[target])}
for name, dist in installed.items():
    for requirement in dist.requires or []:
        dependency = re.split(r"[\s(<>=!~;\[]", requirement, maxsplit=1)[0]
        if dependency in workspace and dependency not in installed:
            raise SystemExit(f"Missing workspace dependency in function payload: {name} -> {dependency}")
PY
rm -rf "$wheels" "$requirements"
echo "Packaged $(ls "$target" | wc -l | tr -d ' ') entries into $target"
