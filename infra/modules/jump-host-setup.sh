#!/bin/sh
# Installs the deployment tools on the jump host. Runs as root through the Custom Script
# extension (jump-host.bicep) and is safe to rerun. __ADMIN_USER__ is replaced by Bicep.
set -eu
user=__ADMIN_USER__
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y curl git docker.io
usermod -aG docker "$user"

command -v az >/dev/null || curl -sL https://aka.ms/InstallAzureCLIDeb | bash
command -v azd >/dev/null || curl -fsSL https://aka.ms/install-azd.sh | bash
command -v uv >/dev/null ||
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

# azd extensions are per user.
for extension in microsoft.foundry azure.ai.evaluations; do
  sudo -u "$user" -H sh -c \
    "azd extension list --installed | grep -q '$extension' || azd extension install '$extension'"
done
