FROM tsl0922/ttyd:latest
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    tzdata \
    curl \
    wget \
    openssh-client \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*
