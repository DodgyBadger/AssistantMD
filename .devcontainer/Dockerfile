FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg build-essential python3-dev ripgrep sudo bubblewrap && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs gh && \
    npm config set fund false && \
    npm config set update-notifier false && \
    npm install -g \
        @anthropic-ai/claude-code \
        @openai/codex \
        @google/gemini-cli && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
