#!/bin/sh
# Prepares services/diagnostics-mcp for deployment without a remote build.
#
# The MCP server depends on workspace packages that aren't published, so Oryx (remote
# build) can't install them. Instead, build the workspace packages as wheels and install
# everything as Linux x86_64 wheels for Python 3.14 into .python_packages, where the
# Functions host loads them from. Resolution uses this machine's configured package index.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
service="$root/services/diagnostics-mcp"
wheels="$service/.python_packages/wheels"
target="$service/.python_packages/lib/site-packages"

rm -rf "$service/.python_packages"
uv build --quiet --wheel --package diagnostics-domain --out-dir "$wheels" --directory "$root"
uv build --quiet --wheel --package diagnostics-mcp --out-dir "$wheels" --directory "$root"
uv pip install --quiet \
  --target "$target" \
  --python-version 3.14 \
  --python-platform x86_64-manylinux_2_28 \
  --only-binary :all: \
  --find-links "$wheels" \
  diagnostics-mcp
rm -rf "$wheels"
echo "Packaged $(ls "$target" | wc -l | tr -d ' ') entries into $target"
