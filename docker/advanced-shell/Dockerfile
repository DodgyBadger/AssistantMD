ARG PYTHON_IMAGE="python:3.13-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca"
ARG NODE_IMAGE="node:24.20.0-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e"
ARG UV_IMAGE="ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1"

FROM ${NODE_IMAGE} AS node-runtime
FROM ${UV_IMAGE} AS uv-runtime
FROM ${PYTHON_IMAGE}

COPY --from=node-runtime /usr/local/ /usr/local/
COPY --from=uv-runtime /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        curl \
        findutils \
        gzip \
        git \
        jq \
        openssh-server \
        procps \
        ripgrep \
        tar \
        unzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

ARG SHELL_USER_ID=1000
ARG SHELL_GROUP_ID=1000

RUN groupadd --gid "${SHELL_GROUP_ID}" assistantmd-shell \
    && useradd \
        --uid "${SHELL_USER_ID}" \
        --gid assistantmd-shell \
        --create-home \
        --home-dir /home/assistantmd-shell \
        --shell /bin/bash \
        assistantmd-shell \
    && passwd --delete assistantmd-shell \
    && mkdir -p \
        /run/sshd \
        /run/assistantmd-shell/host-identity \
        /run/assistantmd-shell/host-public \
        /run/assistantmd-shell/client-public \
        /workspace \
    && chown assistantmd-shell:assistantmd-shell /workspace \
    && chmod 1777 \
        /run/assistantmd-shell/client-public \
        /run/assistantmd-shell/host-public

COPY docker/advanced-shell/sshd_config /etc/ssh/sshd_config
COPY docker/advanced-shell/start-sshd.sh /usr/local/bin/start-assistantmd-shell
COPY docker/advanced-shell/forced_command.py /usr/local/bin/assistantmd-shell-entry

RUN chmod 0755 \
        /usr/local/bin/start-assistantmd-shell \
        /usr/local/bin/assistantmd-shell-entry

EXPOSE 2222

ENTRYPOINT ["/usr/local/bin/start-assistantmd-shell"]
