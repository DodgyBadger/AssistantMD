# Modern, efficient Dockerfile with proper user permissions
# Multi-stage build for smaller final image and better security

#######################################################################
## Stage 1: Build dependencies with UV
#######################################################################
FROM python:3.13-slim as builder

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install UV - fast Python package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set up UV environment - install directly to system Python (safer for Docker)
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/usr/local
ENV UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /app
# Copy dependency files first for better layer caching
COPY ./docker/pyproject.toml /app/
COPY ./docker/uv.lock /app/

# Install dependencies directly to system Python (no venv)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

#######################################################################
## Stage 2: Build Tailwind CSS with Node.js
#######################################################################
FROM node:22-slim as css-builder

WORKDIR /app

# Copy Tailwind configuration and source files
COPY package.json package-lock.json tailwind.config.js ./
COPY static/input.css ./static/input.css
COPY static/*.html static/*.js ./static/

# Install dependencies and build CSS
RUN npm ci && \
    npm run build:css

#######################################################################
## Stage 3: Runtime image - minimal and secure
#######################################################################
FROM python:3.13-slim as runtime

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    tzdata \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create application user with configurable UID/GID for host compatibility
# These build args can be overridden from docker-compose.yml
ARG USER_ID=1000
ARG GROUP_ID=1000

RUN set -eux; \
    group_name="$(getent group "${GROUP_ID}" | cut -d: -f1 || true)"; \
    if [ -z "${group_name}" ]; then \
        group_name=appuser; \
        groupadd -g "${GROUP_ID}" "${group_name}"; \
    fi; \
    if [ "${USER_ID}" != "0" ]; then \
        useradd -u "${USER_ID}" -g "${group_name}" -m -d /home/appuser -s /bin/bash appuser; \
    fi

# Set up application directory
WORKDIR /app

# Copy system Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Drop build-only tooling and caches to keep runtime image lean
RUN rm -f /usr/local/bin/uv && rm -rf /root/.cache

# Copy application code and set ownership
COPY --chown=${USER_ID}:${GROUP_ID} . .

# Copy compiled CSS from css-builder stage
COPY --from=css-builder --chown=${USER_ID}:${GROUP_ID} /app/static/output.css /app/static/output.css

# Create data directory for vaults (will be mounted) 
RUN mkdir -p /app/data && chown ${USER_ID}:${GROUP_ID} /app/data

# Avoid writing .pyc files and ensure instant logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Expose configurable port (documentation only, actual port set by environment)
ARG API_PORT=8000
EXPOSE ${API_PORT}

# Use system Python with uvicorn module
USER appuser
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${API_PORT:-8000}"]

#######################################################################
## Metadata for better container management
#######################################################################
LABEL org.opencontainers.image.title="AssistantMD"
LABEL org.opencontainers.image.description="Automated personal productivity system with AI-powered workflows"
LABEL org.opencontainers.image.version="0.1.0"
LABEL security.non-root-user="appuser"
LABEL security.configurable-uid-gid="true"
