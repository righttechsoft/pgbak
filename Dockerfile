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
    gnupg \
    gpg-agent \
    lsb-release \
    p7zip-full

RUN install -d -m 0755 /etc/apt/keyrings && \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/keyrings/postgresql.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17

RUN add-apt-repository ppa:deadsnakes/ppa
RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get -y install tzdata
RUN apt-get install -y --no-install-recommends python3.13-full python3-pip && rm -f /usr/lib/python3.13/EXTERNALLY-MANAGED /usr/lib/python3/EXTERNALLY-MANAGED

WORKDIR /app
COPY . .

RUN chmod +x add.sh && chmod +x list.sh

RUN python3.13 -m pip install pipenv && pipenv --python 3.13 lock && pipenv sync

EXPOSE 8000

CMD printenv > /etc/cron.d/cron && cat /app/crontab >> /etc/cron.d/cron && chmod 0644 /etc/cron.d/cron && crontab /etc/cron.d/cron && cron && rsyslogd && sleep 2 && pipenv run uvicorn web:app --host 0.0.0.0 --port 8000

