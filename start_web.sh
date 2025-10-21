#!/bin/bash

# Start PgBak Web UI
export DB_PATH="${DB_PATH:-backup.sqlite}"

echo "Starting PgBak Web UI..."
echo "Database: $DB_PATH"
echo "URL: http://localhost:8000"
echo ""

uvicorn web:app --host 0.0.0.0 --port 8000 --reload
