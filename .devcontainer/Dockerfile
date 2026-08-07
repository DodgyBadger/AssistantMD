FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

ARG UV_VERSION=0.12.1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg build-essential python3-dev ripgrep sudo bubblewrap && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs gh && \
    python3 -m pip install --no-cache-dir "uv==${UV_VERSION}" && \
    npm config set fund false && \
    npm config set update-notifier false && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
