FROM debian:bookworm

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
        nmap \
        tcpdump \
        python3 \
        procps \
        dnsmasq \
    && rm -rf /var/lib/apt/lists/*

ENV FOLDER_BIN=/root/bin

COPY ./bin /tmp/bin
RUN mv /tmp/bin $FOLDER_BIN && chmod a+x /root/bin/*.sh /root/bin/*.py
