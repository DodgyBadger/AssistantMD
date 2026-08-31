#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
compose_file="${repository_root}/docker/advanced-shell/compose.development.yml"
key_root="${repository_root}/.advanced-shell/keys"

export ADVANCED_SHELL_KEY_ROOT="${key_root}"
docker compose -f "${compose_file}" restart shell
