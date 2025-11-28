#!/usr/bin/env bash
set -e

echo "🛠  Devcontainer setup starting..."

# In Coder/envbuilder (and local devcontainers), CWD = repo root:
#   /workspaces/AssistantMD
REPO_DIR="$(pwd)"
echo "📂 Repo directory detected as: ${REPO_DIR}"

# Make /app point to the repo, so runtime paths work the same as prod
if [ ! -e "/app" ]; then
  echo "📂 Creating /app symlink to ${REPO_DIR}..."
  sudo ln -s "${REPO_DIR}" /app
else
  echo "ℹ️ /app already exists, leaving it as-is."
fi

# Upgrade pip tooling
python3 -m pip install --upgrade pip setuptools wheel

# Install uv if you actually use it
python3 -m pip install --no-cache-dir uv

# Install your package from docker/pyproject.toml
if [ -f "${REPO_DIR}/docker/pyproject.toml" ]; then
  echo "📦 Installing editable package from ${REPO_DIR}/docker[dev]..."
  python3 -m pip install --no-cache-dir -e "${REPO_DIR}/docker[dev]"
else
  echo "⚠️  ${REPO_DIR}/docker/pyproject.toml not found; skipping package install."
fi

echo "✅ Devcontainer setup complete. Use /app as the project root."
