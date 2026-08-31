#!/usr/bin/env bash
set -u

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
compose_file="${repository_root}/docker/advanced-shell/compose.development.yml"
key_root="${repository_root}/.advanced-shell/keys"
diagnostic_log="${repository_root}/scripts/advanced_shell_development.latest.log"

export ADVANCED_SHELL_KEY_ROOT="${key_root}"
exec > >(tee "${diagnostic_log}") 2>&1

echo "compose state"
docker compose -f "${compose_file}" ps --all

echo "container health"
for service in key-init shell readiness; do
    container_id=$(docker compose -f "${compose_file}" ps -a -q "${service}")
    if [[ -n ${container_id} ]]; then
        echo "${service}:"
        docker inspect --format '{{json .State}}' "${container_id}"
    fi
done

echo "service logs"
docker compose -f "${compose_file}" logs --no-color key-init shell readiness

if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
    chown "${SUDO_UID}:${SUDO_GID}" "${diagnostic_log}" || true
fi

echo "wrote ${diagnostic_log}"
