FROM tsl0922/ttyd:latest
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    tzdata \
    curl \
    wget \
    openssh-client \
    iputils-ping \
    dnsutils \
    traceroute \
    iproute2 \
    netcat-openbsd \
    vim \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
