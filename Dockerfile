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
    gpg-agent \
    p7zip-full

RUN sh -c 'echo "deb https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'

RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-16

RUN add-apt-repository ppa:deadsnakes/ppa
RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get -y install tzdata
RUN apt-get install -y --no-install-recommends python3.11-full python3-pip

WORKDIR /app
COPY . .

RUN python3.11 -m pip install pipenv && pipenv install --python 3.11

CMD printenv > /etc/cron.d/cron && cat /app/crontab >> /etc/cron.d/cron && chmod 0644 /etc/cron.d/cron && crontab /etc/cron.d/cron && cron && rsyslogd && sleep 2 && tail -F /var/log/syslog

