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
rm -rf "$wheels" "$requirements"
echo "Packaged $(ls "$target" | wc -l | tr -d ' ') entries into $target"
