#!/usr/bin/env bash
# DO NOT use set -e while debugging; we want to see where it breaks
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
# This works no matter where we run the script from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
echo "Repo dir: ${REPO_DIR}"

# 3. Try to create /app symlink (log errors, don't hard-fail)
if [ -L "/app" ]; then
  echo "/app is already a symlink -> $(readlink /app || true)"
elif [ -e "/app" ]; then
  echo "WARNING: /app exists and is not a symlink; leaving it alone."
else
  echo "Creating /app symlink to ${REPO_DIR}..."
  if ln -s "${REPO_DIR}" /app; then
    echo "Symlink /app -> ${REPO_DIR} created."
  else
    echo "ERROR: failed to create symlink /app -> ${REPO_DIR}"
  fi
fi

# 4. Upgrade pip tooling (log, but don't fail hard)
echo "Upgrading pip/setuptools/wheel..."
if ! python3 -m pip install --upgrade pip setuptools wheel; then
  echo "WARNING: failed to upgrade pip tooling."
fi

# 5. Install uv if missing
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  if ! python3 -m pip install --no-cache-dir uv; then
    echo "WARNING: failed to install uv."
  fi
fi

# 6. Install your package from docker/pyproject.toml
if [ -f "${REPO_DIR}/docker/pyproject.toml" ]; then
  echo "Installing editable package from ${REPO_DIR}/docker[dev]..."
  if ! python3 -m pip install --no-cache-dir -e "${REPO_DIR}/docker[dev]"; then
    echo "ERROR: pip install -e ${REPO_DIR}/docker[dev] failed."
    exit 1
  fi
else
  echo "WARNING: ${REPO_DIR}/docker/pyproject.toml not found; skipping install."
fi

echo "=== setup.sh: finished successfully ==="
