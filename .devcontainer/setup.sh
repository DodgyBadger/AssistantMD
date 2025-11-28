#!/usr/bin/env bash
set -e

echo "🛠  Devcontainer setup starting..."

# The devcontainer starts with CWD at the repo root, which is:
#   /workspaces/<repo-name>
REPO_DIR="$(pwd)"

echo "📂 Repo directory detected as: ${REPO_DIR}"

# 1. Ensure /app points at the repo root
if [ ! -e "/app" ]; then
  echo "📂 Creating /app symlink to ${REPO_DIR}..."
  sudo ln -s "${REPO_DIR}" /app
else
  echo "ℹ️ /app already exists, leaving it as-is."
fi

# 2. Install Python tooling & your package from the real path
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir uv

# Use the *real* path to the project being installed
if [ -f "${REPO_DIR}/docker/pyproject.toml" ]; then
  echo "📦 Installing editable package from ${REPO_DIR}/docker[dev]..."
  python3 -m pip install --no-cache-dir -e "${REPO_DIR}/docker[dev]"
else
  echo "⚠️  ${REPO_DIR}/docker/pyproject.toml not found; skipping package install."
fi

echo "✅ Devcontainer setup complete. Runtime project root is /app."
