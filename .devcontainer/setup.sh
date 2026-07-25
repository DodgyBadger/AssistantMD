#!/usr/bin/env bash
set -uo pipefail

echo "=== setup.sh: starting ==="
echo "CWD: $(pwd)"
echo "User: $(id)"
# Note: invoked by devcontainer postCreateCommand

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

# 3. Use uv to sync dependencies from root pyproject.toml + uv.lock
#    into system Python (/usr/local), matching production image behavior.
if [ -f "${REPO_DIR}/pyproject.toml" ] && [ -f "${REPO_DIR}/uv.lock" ]; then
  echo "Syncing dependencies with uv (including dev deps)..."
  (
    cd "${REPO_DIR}"
    unset VIRTUAL_ENV
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    uv sync --extra dev --no-install-project || echo "WARNING: uv sync failed; continuing"
  )
  # Remove stale project venv to avoid accidental interpreter/path drift.
  if [ -d "${REPO_DIR}/.venv" ]; then
    rm -rf "${REPO_DIR}/.venv" || echo "WARNING: failed to remove .venv"
  fi
else
  echo "WARNING: pyproject.toml or uv.lock not found; skipping uv sync."
fi

# 4. Install Node.js dependencies and build Tailwind CSS
if [ -f "${REPO_DIR}/package.json" ]; then
  echo "Installing npm dependencies from lockfile..."
  cd "${REPO_DIR}"
  npm ci || echo "WARNING: npm ci failed"
  
  echo "Building Tailwind CSS..."
  npm run build:css || echo "WARNING: npm run build:css failed"
else
  echo "WARNING: package.json not found; skipping npm install and Tailwind build."
fi

# 5. Install Playwright Chromium and required OS deps for browser-tool parity
echo "Ensuring Playwright Chromium runtime is installed..."
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright}"
python3 -m playwright install --with-deps chromium || echo "WARNING: Playwright browser install failed"

# 6. Register the Logfire MCP endpoint. OAuth login remains an interactive step.
LOGFIRE_MCP_URL="https://logfire-eu.pydantic.dev/mcp"
if command -v codex >/dev/null 2>&1; then
  if codex mcp get logfire >/dev/null 2>&1; then
    echo "Logfire MCP is already registered."
  else
    echo "Registering Logfire MCP..."
    codex mcp add logfire --url "${LOGFIRE_MCP_URL}" \
      || echo "WARNING: failed to register Logfire MCP"
  fi
  echo "To authenticate Logfire MCP, run: codex mcp login logfire"
else
  echo "WARNING: codex CLI not found; skipping Logfire MCP registration."
fi

echo "=== setup.sh: finished ==="
