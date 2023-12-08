FROM ubuntu:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    curl \
    ca-certificates \
    git \
    wget \
    libpq-dev \
    zlib1g-dev \
    screen \
    cron \
    rsyslog \
    nano \
    systemd  \
    libpam-systemd \
    gpg-agent

RUN sh -c 'echo "deb https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'

RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-16

ENTRYPOINT ["top", "-b"]