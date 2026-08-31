FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        openssh-client \
        procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /smoke

ENTRYPOINT ["/bin/sleep", "infinity"]
