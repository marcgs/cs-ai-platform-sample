#!/bin/sh
# Installs the deployment tools on the jump host. Runs as root through the Custom Script
# extension (jump-host.bicep) and is safe to rerun. __ADMIN_USER__ is replaced by Bicep.
set -eu
user=__ADMIN_USER__
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y curl git docker.io
usermod -aG docker "$user"

# Download to a file first: sh has no pipefail, so a failed download piped into a shell would pass.
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
fetch() { curl -fsSL --retry 3 -o "$installer" "$1"; }

# Plain if blocks: set -e doesn't stop on a failure inside an || or && list.
if ! command -v az >/dev/null; then
  fetch https://aka.ms/InstallAzureCLIDeb
  bash "$installer"
fi
if ! command -v azd >/dev/null; then
  fetch https://aka.ms/install-azd.sh
  bash "$installer"
fi
if ! command -v uv >/dev/null; then
  fetch https://astral.sh/uv/install.sh
  env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "$installer"
fi

# azd extensions are per user.
for extension in microsoft.foundry azure.ai.evaluations; do
  sudo -u "$user" -H sh -c \
    "azd extension list --installed | grep -q '$extension' || azd extension install '$extension'"
done
