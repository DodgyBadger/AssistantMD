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

# Workspace is /app, same as production
REPO_DIR="/app"
echo "Repo dir: ${REPO_DIR}"

# 2. Install/upgrade uv
echo "Ensuring uv is installed..."
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --no-cache-dir uv || echo "WARNING: failed to install uv"
fi

# 3. Use uv to sync dependencies from docker/pyproject.toml + uv.lock
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

# 4. Install Node.js dependencies and build Tailwind CSS
if [ -f "${REPO_DIR}/package.json" ]; then
  echo "Installing npm dependencies..."
  cd "${REPO_DIR}"
  npm install || echo "WARNING: npm install failed"
  
  echo "Building Tailwind CSS..."
  npm run build:css || echo "WARNING: npm run build:css failed"
else
  echo "WARNING: package.json not found; skipping npm install and Tailwind build."
fi

echo "=== setup.sh: finished ==="