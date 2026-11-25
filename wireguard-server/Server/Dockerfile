FROM debian:bookworm AS base

LABEL maintainer="Zebroo GmbH"

WORKDIR /root

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y \
        wireguard \
        wireguard-tools \
        iproute2 \
        iptables \
        inetutils-ping \
        net-tools \
        python3 \
        procps \
        dnsmasq \
    && rm -rf /var/lib/apt/lists/*

ENV FOLDER_BIN=/root/bin

COPY ./bin /tmp/bin
RUN mv /tmp/bin $FOLDER_BIN && chmod a+x /root/bin/*.sh /root/bin/*.py

# Troubleshooting image: WG_BUILD_TARGET=debug in .env.
FROM base AS debug
RUN apt-get update && \
    apt-get install -y nmap tcpdump \
    && rm -rf /var/lib/apt/lists/*

# Production image. Last stage, so a plain "docker build" produces it too.
FROM base AS runtime
