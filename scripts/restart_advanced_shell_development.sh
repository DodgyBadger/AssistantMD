#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
compose_file="${repository_root}/docker/advanced-shell/compose.development.yml"
if [[ -n ${CONTAINER_SYSTEM_ROOT:-} ]]; then
    state_root="${CONTAINER_SYSTEM_ROOT}/advanced-shell"
elif [[ -n ${ASSISTANTMD_DEV_RUNTIME_ROOT:-} ]]; then
    state_root="${ASSISTANTMD_DEV_RUNTIME_ROOT}/system/advanced-shell"
else
    state_root="${repository_root}/system/advanced-shell"
fi
companion_key_root="${repository_root}/.advanced-shell/companion-keys"

export ADVANCED_SHELL_CLIENT_PUBLIC_KEY="${state_root}/client_identity.pub"
export ADVANCED_SHELL_COMPANION_HOST_KEY="${companion_key_root}/ssh_host_ed25519_key"
docker compose -f "${compose_file}" restart shell
