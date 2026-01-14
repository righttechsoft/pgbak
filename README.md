# pgbak

PostgreSQL backup automation tool with Backblaze B2 cloud storage integration.

## Features

- Configure multiple PostgreSQL servers for backup
- Schedule backups at specified frequencies (hourly cron job)
- Compress backups using 7z with LZMA2 and optional AES encryption
- Upload backup files to Backblaze B2 storage
- Support for SQL (plain text) and binary (PostgreSQL custom) backup formats
- Log backup results and track file sizes
- Health check integration with separate URLs for start/success/fail events (healthchecks.io compatible)
- **Web UI** for easy server management (FastAPI-based)
  - Run backups manually with one click
  - Relative time display for last backup ("2 hours ago")
  - Password visibility toggle
- **CLI** for scripting and automation
- Centralized logging via Mezmo (LogDNA)

## Quick Start with Docker

```bash
# Build the image
docker build -t pgbak .

# Run the container
docker run -d -p 8000:8000 \
  -e MEZMO_INGESTION_KEY=your_key \
  -e B2_KEY_ID=your_b2_key_id \
  -e B2_APP_KEY=your_b2_app_key \
  -e B2_BUCKET=your_bucket_name \
  -v pgbak-data:/app \
  pgbak
```

Access the Web UI at `http://localhost:8000`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MEZMO_INGESTION_KEY` | Yes* | Mezmo ingestion key for logging |
| `B2_KEY_ID` | No | Default Backblaze B2 key ID |
| `B2_APP_KEY` | No | Default Backblaze B2 application key |
| `B2_BUCKET` | No | Default Backblaze B2 bucket name |
| `ARCHIVE_PASSWORD` | No | Default password for encrypting archives |
| `DB_PATH` | No | SQLite database path (default: backup.sqlite) |

*Set to empty string if not using Mezmo logging

## Usage

### Web UI (Recommended)

The web interface runs automatically in Docker on port 8000. Use it to:
- View all configured servers and their backup status
- Add, edit, or delete server configurations
- View backup logs and history

### Command Line Interface

```bash
# Run with pipenv
pipenv run python main.py [command] [options]

# Or use helper scripts
./add.sh    # Add a new server
./list.sh   # List all servers
```

**Available commands:**

| Command | Description |
|---------|-------------|
| `add` | Add a new server configuration (interactive) |
| `edit` | Edit an existing server configuration |
| `del` | Delete a server configuration |
| `list` | List all configured servers |
| `logs` | Display backup logs for a selected server |
| `run` | Run backups for all configured servers |

**Options for `run` command:**

```bash
# Force backup regardless of frequency setting
python main.py run --force

# Backup specific server only
python main.py run --server <id>

# Use binary format instead of SQL
python main.py run --format binary
```

## Server Configuration

Each server configuration includes:

| Field | Required | Description |
|-------|----------|-------------|
| `connection_string` | Yes | PostgreSQL URI (e.g., `postgresql://user:pass@host:5432/db`) |
| `frequency_hrs` | Yes | Backup frequency in hours |
| `archive_name` | No | Base name for backup files |
| `archive_password` | No | Password for 7z encryption (overrides env default) |
| `B2_KEY_ID` | No | Server-specific B2 key (overrides env default) |
| `B2_APP_KEY` | No | Server-specific B2 app key (overrides env default) |
| `B2_BUCKET` | No | Server-specific B2 bucket (overrides env default) |
| `hc_url_start` | No | Healthcheck URL to call when backup starts |
| `hc_url_success` | No | Healthcheck URL to call on successful backup |
| `hc_url_fail` | No | Healthcheck URL to call on backup failure |

## How It Works

1. **Cron Job**: Runs `python main.py run` every hour
2. **Frequency Check**: Only backs up servers that have exceeded their frequency threshold
3. **Backup Process**:
   - Calls `hc_url_start` (if configured)
   - Runs `pg_dump` piped directly to `7z` for streaming compression
   - Uploads compressed archive to Backblaze B2
   - Validates backup size (minimum 4KB, alerts on >10% size change)
   - Logs result and calls `hc_url_success` or `hc_url_fail` accordingly

## Requirements

- Python 3.13
- PostgreSQL client (pg_dump)
- 7zip (p7zip-full)
- Backblaze B2 account

## Local Development

```bash
# Install dependencies
pip install pipenv
pipenv install

# Set environment variables
export MEZMO_INGESTION_KEY=""  # Empty to disable Mezmo
export DB_PATH=backup.sqlite

# Run web UI locally
pipenv run uvicorn web:app --reload --port 8000

# Or use the helper script
./start_web.sh
```

## License

This project is licensed under the [MIT License](LICENSE).
