# syntax=docker/dockerfile:1

##############################################################################
# base - OS packages needed at runtime. Shared by both stages, so the slow
# apt work (pgdg + deadsnakes repos) is done once and cached for both.
##############################################################################
FROM ubuntu:24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PIPENV_VENV_IN_PROJECT=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release software-properties-common tzdata \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /etc/apt/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.13-full \
        python3-pip \
        postgresql-client-17 \
        p7zip-full \
        cron \
        rsyslog \
    && rm -f /usr/lib/python3.13/EXTERNALLY-MANAGED /usr/lib/python3/EXTERNALLY-MANAGED \
    && rm -rf /var/lib/apt/lists/*

##############################################################################
# builder - compiles the virtualenv. Compilers and -dev headers live here only,
# so they never ship in the final image.
##############################################################################
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev zlib1g-dev python3.13-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# only the dependency manifests, so editing main.py does not rebuild the venv
COPY Pipfile Pipfile.lock ./
RUN python3.13 -m pip install --no-cache-dir pipenv \
    && pipenv --python 3.13 lock \
    && pipenv sync

##############################################################################
# runtime
##############################################################################
FROM base AS runtime

WORKDIR /app

# pipenv itself is kept so `pipenv run ...` keeps working inside the container
RUN python3.13 -m pip install --no-cache-dir pipenv

COPY --from=builder /app/.venv /app/.venv
COPY . .

RUN chmod +x add.sh list.sh

EXPOSE 8000

CMD printenv > /etc/cron.d/cron && cat /app/crontab >> /etc/cron.d/cron && chmod 0644 /etc/cron.d/cron && crontab /etc/cron.d/cron && cron && rsyslogd && sleep 2 && pipenv run uvicorn web:app --host 0.0.0.0 --port 8000
