#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
system_root=${CONTAINER_SYSTEM_ROOT:-"${repository_root}/system"}
state_root="${system_root}/advanced-shell"
companion_key_root=${ADVANCED_SHELL_COMPANION_KEY_ROOT:-"${repository_root}/.advanced-shell/companion-keys"}
client_identity="${state_root}/client_identity"
companion_host_identity="${companion_key_root}/ssh_host_ed25519_key"

command -v ssh-keygen >/dev/null 2>&1 || {
    echo "ERROR: ssh-keygen is required." >&2
    exit 1
}

mkdir -p "${state_root}" "${companion_key_root}"
chmod 0700 "${state_root}" "${companion_key_root}"

if [[ ! -s "${client_identity}" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${client_identity}"
elif [[ ! -s "${client_identity}.pub" ]]; then
    ssh-keygen -y -f "${client_identity}" > "${client_identity}.pub"
fi

if [[ ! -s "${companion_host_identity}" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "${companion_host_identity}"
fi

host_public_key=$(ssh-keygen -y -f "${companion_host_identity}")
known_hosts_temp=$(mktemp "${state_root}/known_hosts.XXXXXX")
cleanup() {
    rm -f -- "${known_hosts_temp}"
}
trap cleanup EXIT
printf '[assistantmd-shell]:2222 %s\n' "${host_public_key}" > "${known_hosts_temp}"
chmod 0644 "${known_hosts_temp}"
mv -f -- "${known_hosts_temp}" "${state_root}/known_hosts"
trap - EXIT

chmod 0600 "${client_identity}" "${companion_host_identity}"
chmod 0644 "${client_identity}.pub" "${state_root}/known_hosts"

echo "Advanced shell identities are provisioned."
echo "AssistantMD client state: ${state_root}"
echo "Companion host identity: ${companion_key_root}"
