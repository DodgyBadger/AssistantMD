FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

# Optional host-aligned user (defaults to 1000:1001); adjust via build args.
ARG UID=1000
ARG GID=1001

# Install Node.js (for global CLI tooling), GitHub CLI, and common build tooling
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg build-essential python3-dev sudo && \
    # GitHub CLI repository
    mkdir -p -m 755 /etc/apt/keyrings && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs gh && \
    # Create coder user with passwordless sudo
    if ! getent group ${GID} >/dev/null; then groupadd -g ${GID} coder; fi && \
    if ! id -u ${UID} >/dev/null 2>&1; then useradd -u ${UID} -g ${GID} -m -s /bin/bash coder; fi && \
    usermod -aG sudo coder && \
    echo "coder ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    npm config set fund false && \
    npm config set update-notifier false && \
    npm install -g \
        @anthropic-ai/claude-code@2.0.55 \
        @openai/codex@0.63.0 \
        @google/gemini-cli@0.18.4 && \
    rm -rf /var/lib/apt/lists/*

# Defaults for the devcontainer user
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
