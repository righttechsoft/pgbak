# CLAUDE.md - Project Guide for AI Assistants

## Project Overview

**pgbak** is a PostgreSQL backup automation tool that creates compressed, encrypted backups and uploads them to Backblaze B2 cloud storage. It runs as a Docker container with scheduled cron jobs and provides both CLI and Web UI interfaces.

## Architecture

```
pgbak/
├── main.py                 # CLI entry point and backup logic
├── database.py             # SQLite database operations
├── web.py                  # FastAPI web interface
├── single_instance_helper.py # Prevents concurrent execution
├── test_pgbak.py           # Self-check for the backup guards (no framework, asserts)
├── Dockerfile              # Multi-stage container build (Python 3.13)
├── .dockerignore           # Keeps .git / venv / sqlite out of the build context
├── Pipfile                 # Python dependencies (Python 3.13)
├── crontab                 # Hourly backup schedule
├── templates/              # Jinja2 HTML templates for web UI
│   ├── index.html          # Server list page
│   ├── form.html           # Add/edit server form
│   └── logs.html           # Backup logs viewer
├── static/                 # Static assets (favicon)
└── *.sh                    # Utility shell scripts
```

## Core Components

### main.py
- **Entry point** for CLI operations
- **Commands**: `add`, `del`, `edit`, `list`, `logs`, `run`
- **Backup process**:
  1. Reads server configs from SQLite
  2. Checks if backup frequency threshold reached
  3. Calls `hc_url_start` (if configured)
  4. Runs `pg_dump` piped to `7z` for compression
  5. Uploads to Backblaze B2
  6. Logs result to database (updates `last_backup` and `last_backup_result`)
  7. Calls `hc_url_success` or `hc_url_fail` accordingly
- **Backup formats**: `sql` (plain text) or `binary` (PostgreSQL custom format)
- Uses `SingleInstance` to prevent concurrent runs

### database.py
- SQLite database wrapper class
- **Tables**:
  - `servers`: Server configurations
  - `backup_log`: Backup history with timestamp, result, file_size, success flag
- Database path configurable via `DB_PATH` env var (default: `backup.sqlite`)
- **Schema migration**: Automatically removes obsolete columns and migrates legacy `dms_id` to `hc_url_success`

#### Server Configuration Fields
| Field | Description |
|-------|-------------|
| `connection_string` | PostgreSQL URI |
| `frequency_hrs` | Backup frequency in hours |
| `B2_KEY_ID` | Backblaze B2 key ID (overrides env) |
| `B2_APP_KEY` | Backblaze B2 app key (overrides env) |
| `B2_BUCKET` | Backblaze B2 bucket (overrides env) |
| `archive_name` | Base name for backup files |
| `archive_password` | 7z encryption password (overrides env) |
| `hc_url_start` | Healthcheck URL called on backup start |
| `hc_url_success` | Healthcheck URL called on success |
| `hc_url_fail` | Healthcheck URL called on failure |
| `last_backup` | Timestamp of last backup attempt |
| `last_backup_result` | Result of last backup (Success/Failed) |

### web.py
- FastAPI application on port 8000
- **Endpoints**:
  - `GET /` - Server list with relative time display for last backup
  - `GET/POST /add` - Add server
  - `GET/POST /edit/{id}` - Edit server
  - `POST /delete/{id}` - Delete server
  - `POST /run/{id}` - Trigger manual backup (checks lock file to prevent concurrent runs)
  - `GET /logs/{id}` - View backup logs with formatted timestamps
- **Jinja2 Filters**:
  - `relative_time` - Converts timestamp to "X minutes ago" format
  - `format_timestamp` - Converts timestamp to "DD Mon YY HH:MM (relative time)" format
- **UI Features**:
  - Password visibility toggle (eye button)
  - Favicon support via `/static/` mount
  - Run button for manual backups with status feedback
  - Relative time display for last backup column

### Dockerfile
Multi-stage, built for fast redeploys:
- **base**: Ubuntu 24.04 + Python 3.13 (deadsnakes PPA), PostgreSQL client 17, 7zip, cron, rsyslog.
  Both later stages start from this, so the slow apt work is done and cached once.
- **builder**: adds compilers/headers (`build-essential`, `libpq-dev`, `python3.13-dev`) and builds
  the virtualenv from `Pipfile`/`Pipfile.lock` **only**. Editing application code does not
  invalidate this layer, so a code-only redeploy skips dependency installation entirely.
- **runtime**: copies the finished `/app/.venv` from the builder, then the source. Compilers never
  reach the final image.
- `PIPENV_VENV_IN_PROJECT=1` puts the venv at `/app/.venv` so it can be copied between stages;
  `pipenv run ...` still works inside the container.
- Dependencies are re-locked only when `Pipfile`/`Pipfile.lock` change. To force a refresh:
  `docker build --no-cache .`
- **Startup**: Sets up cron, starts rsyslog, runs uvicorn web server

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MEZMO_INGESTION_KEY` | No | Mezmo (LogDNA) logging key; logging to stdout happens regardless |
| `B2_KEY_ID` | No | Default Backblaze B2 key ID |
| `B2_APP_KEY` | No | Default Backblaze B2 app key |
| `B2_BUCKET` | No | Default Backblaze B2 bucket |
| `ARCHIVE_PASSWORD` | No | Default archive encryption password |
| `DB_PATH` | No | SQLite database path (default: backup.sqlite) |
| `LOG_HOSTNAME` | No | Hostname for Mezmo logging |
| `BACKUP_TIMEOUT_SEC` | No | Kill a dump that runs longer than this (default: 14400 = 4h) |

## Key Workflows

### Running Backups
```bash
# Via cron (hourly)
pipenv run python main.py run

# Force backup regardless of frequency
pipenv run python main.py run --force

# Specific server only
pipenv run python main.py run --server <id>

# Binary format backup
pipenv run python main.py run --format binary
```

### Docker Deployment
```bash
docker build -t pgbak .
docker run -d -p 8000:8000 \
  -e MEZMO_INGESTION_KEY=... \
  -e B2_KEY_ID=... \
  -e B2_APP_KEY=... \
  -e B2_BUCKET=... \
  -v /path/to/data:/app/backup.sqlite \
  pgbak
```

## Important Implementation Details

1. **Single Instance**: `SingleInstance('pgbak')` prevents concurrent backup runs using file locking.
   Only the `run` command takes the lock, so the config commands still work during a backup
2. **Backup Size Validation**: Fails the backup (before upload) if the archive is >10% smaller than the last successful one; only warns if it is >10% larger
3. **Dump Exit Code**: `pg_dump`'s exit code is checked (after an explicit `wait()`), so a dump that
   dies halfway cannot be compressed and uploaded as a "successful" backup
4. **Timeout**: the dump/compress pipeline is killed after `BACKUP_TIMEOUT_SEC`; without it a hung
   `pg_dump` would hold the single-instance lock forever and silently starve every later cron run
5. **No shell**: `pg_dump` and `7z` are spawned as argument lists (no `shell=True`), so passwords
   containing shell metacharacters or spaces are passed through intact
6. **archive_name**: required, and must be unique within a run - two servers sharing a name would
   append into the same 7z archive and overwrite each other in B2
7. **Health Checks**: Supports separate URLs for start/success/fail events (healthchecks.io compatible)
8. **Compression**: Uses 7z with LZMA2, optional AES encryption (`-mhe=on`)
9. **Schema Migration**: Database automatically migrates on startup to handle schema changes

## Common Tasks

### Adding a new server via CLI
```bash
pipenv run python main.py add
# Interactive prompts for connection_string, frequency, B2 settings, etc.
```

### Viewing logs
```bash
pipenv run python main.py logs
# Select server from list to view backup history
```

### Web UI
Access at `http://localhost:8000` when container is running.
