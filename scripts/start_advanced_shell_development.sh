#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
compose_file="${repository_root}/docker/advanced-shell/compose.development.yml"
key_root="${repository_root}/.advanced-shell/keys"
host_port=${ADVANCED_SHELL_HOST_PORT:-22222}
client_host=${ADVANCED_SHELL_CLIENT_HOST:-127.0.0.1}

mkdir -p "${key_root}"
if [[ ! -s "${key_root}/assistantmd_shell_client" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${key_root}/assistantmd_shell_client"
fi
if [[ ! -s "${key_root}/ssh_host_ed25519_key" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${key_root}/ssh_host_ed25519_key"
fi

host_public_key=$(ssh-keygen -y -f "${key_root}/ssh_host_ed25519_key")
cp "${key_root}/assistantmd_shell_client" \
    "${key_root}/assistantmd_shell_readiness_client"
{
    printf '[127.0.0.1]:%s %s\n' "${host_port}" "${host_public_key}"
    printf '[localhost]:%s %s\n' "${host_port}" "${host_public_key}"
    printf '[host.docker.internal]:%s %s\n' "${host_port}" "${host_public_key}"
    printf '[%s]:%s %s\n' "${client_host}" "${host_port}" "${host_public_key}"
    printf '[shell]:2222 %s\n' "${host_public_key}"
} > "${key_root}/known_hosts"
# Rootless/user-mapped containers may not map their root identity to the host
# owner. The companion copies the source host key into tmpfs and restores 0600
# before sshd reads it, so the read-only bind source must remain world-readable.
chmod 0600 "${key_root}/assistantmd_shell_client"
chmod 0644 \
    "${key_root}/assistantmd_shell_readiness_client" \
    "${key_root}/assistantmd_shell_client.pub" \
    "${key_root}/ssh_host_ed25519_key" \
    "${key_root}/known_hosts"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
    chown -R "${SUDO_UID}:${SUDO_GID}" "${repository_root}/.advanced-shell"
fi

export ADVANCED_SHELL_KEY_ROOT="${key_root}"
docker compose -f "${compose_file}" up -d --build --force-recreate --wait

echo "Persistent advanced-shell companion is running."
echo "Workspace volume: assistantmd-advanced-shell-dev_workspace"
echo "Home volume: assistantmd-advanced-shell-dev_home"
echo "Client key root: ${key_root}"
echo "Probe from the Docker host with:"
echo "  ASSISTANTMD_SHELL_HOST=${client_host} ASSISTANTMD_SHELL_PORT=${host_port} ASSISTANTMD_SHELL_HOST_KEY_ALIAS='[127.0.0.1]:${host_port}' ASSISTANTMD_SHELL_KEY_ROOT=${key_root} uv run python validation/scenarios/experiments/advanced_shell_tool_probe.py"
