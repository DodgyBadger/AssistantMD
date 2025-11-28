#!/usr/bin/env bash
set -uo pipefail

echo "=== setup.sh: starting ==="
echo "CWD: $(pwd)"
echo "User: $(id)"

# 1. Check that python3 is available
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found on PATH."
  exit 1
fi

# 2. Determine repo dir (parent of .devcontainer)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
echo "Repo dir: ${REPO_DIR}"

# 3. Ensure /app points to the repo root (force replace if needed)
if [ -L "/app" ]; then
  echo "/app is a symlink -> $(readlink /app || true); replacing with ${REPO_DIR}"
  rm -f /app
elif [ -e "/app" ]; then
  echo "WARNING: /app exists as a regular file/dir; replacing with symlink."
  rm -rf /app
fi

echo "Creating /app symlink to ${REPO_DIR}..."
if ln -s "${REPO_DIR}" /app; then
  echo "Symlink /app -> ${REPO_DIR} created."
else
  echo "ERROR: failed to create symlink /app -> ${REPO_DIR}"
fi

# 4. Install/upgrade uv
echo "Ensuring uv is installed..."
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --no-cache-dir uv || echo "WARNING: failed to install uv"
fi

# 5. Use uv to sync dependencies from docker/pyproject.toml + uv.lock
if [ -f "${REPO_DIR}/docker/pyproject.toml" ] && [ -f "${REPO_DIR}/docker/uv.lock" ]; then
  echo "Syncing dependencies with uv (no dev deps)..."
  (
    cd "${REPO_DIR}/docker"
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_CACHE_DIR=/tmp/uv-cache \
    uv sync --no-install-project --no-dev || echo "WARNING: uv sync failed; continuing"
  )
else
  echo "WARNING: docker/pyproject.toml or docker/uv.lock not found; skipping uv sync."
fi

echo "=== setup.sh: finished (no editable docker install) ==="
