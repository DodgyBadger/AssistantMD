FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        openssh-server \
        procps \
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
    && mkdir -p /run/sshd /workspace \
    && chown assistantmd-shell:assistantmd-shell /workspace

COPY docker/advanced-shell/sshd_config /etc/ssh/sshd_config
COPY docker/advanced-shell/start-sshd.sh /usr/local/bin/start-assistantmd-shell
COPY docker/advanced-shell/forced_command.py /usr/local/bin/assistantmd-shell-entry

RUN chmod 0755 \
        /usr/local/bin/start-assistantmd-shell \
        /usr/local/bin/assistantmd-shell-entry

EXPOSE 2222

ENTRYPOINT ["/usr/local/bin/start-assistantmd-shell"]
