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
host_port=${ADVANCED_SHELL_HOST_PORT:-22222}
client_host=${ADVANCED_SHELL_CLIENT_HOST:-127.0.0.1}

mkdir -p "${state_root}" "${companion_key_root}"
if [[ ! -s "${state_root}/client_identity" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${state_root}/client_identity"
fi
if [[ ! -s "${companion_key_root}/ssh_host_ed25519_key" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${companion_key_root}/ssh_host_ed25519_key"
fi

host_public_key=$(ssh-keygen -y -f "${companion_key_root}/ssh_host_ed25519_key")
{
    printf '[127.0.0.1]:%s %s\n' "${host_port}" "${host_public_key}"
    printf '[localhost]:%s %s\n' "${host_port}" "${host_public_key}"
    printf '[host.docker.internal]:%s %s\n' "${host_port}" "${host_public_key}"
    printf '[%s]:%s %s\n' "${client_host}" "${host_port}" "${host_public_key}"
    printf '[shell]:2222 %s\n' "${host_public_key}"
    printf '[assistantmd-shell]:2222 %s\n' "${host_public_key}"
} > "${state_root}/known_hosts"
# Rootless/user-mapped containers may not map their root identity to the host
# owner. The companion copies the source host key into tmpfs and restores 0600
# before sshd reads it, so the read-only bind source must remain world-readable.
chmod 0700 "${state_root}" "${companion_key_root}"
chmod 0600 "${state_root}/client_identity"
chmod 0644 \
    "${state_root}/client_identity.pub" \
    "${state_root}/known_hosts" \
    "${companion_key_root}/ssh_host_ed25519_key"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
    chown -R "${SUDO_UID}:${SUDO_GID}" \
        "${state_root}" \
        "${companion_key_root}"
fi

export ADVANCED_SHELL_CLIENT_PUBLIC_KEY="${state_root}/client_identity.pub"
export ADVANCED_SHELL_COMPANION_HOST_KEY="${companion_key_root}/ssh_host_ed25519_key"
docker compose -f "${compose_file}" up -d --build --force-recreate --wait --remove-orphans

echo "Persistent advanced-shell companion is running."
echo "Workspace volume: assistantmd-advanced-shell-dev_workspace"
echo "Home volume: assistantmd-advanced-shell-dev_home"
echo "AssistantMD shell state: ${state_root}"
echo "Companion host identity: ${companion_key_root}"
echo "Add these values to .env and restart AssistantMD:"
echo "  ASSISTANTMD_EXECUTION_MODE=advanced"
echo "  ASSISTANTMD_SHELL_HOST=${client_host}"
echo "  ASSISTANTMD_SHELL_PORT=${host_port}"
echo "  ASSISTANTMD_SHELL_HOST_KEY_ALIAS=[${client_host}]:${host_port}"
echo "Direct experimental probe:"
echo "  ASSISTANTMD_SHELL_HOST=${client_host} ASSISTANTMD_SHELL_PORT=${host_port} ASSISTANTMD_SHELL_HOST_KEY_ALIAS='[${client_host}]:${host_port}' ASSISTANTMD_SHELL_KEY_ROOT=${state_root} uv run python validation/scenarios/experiments/advanced_shell_tool_probe.py"
