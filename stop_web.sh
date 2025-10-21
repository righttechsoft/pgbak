#!/bin/bash

# Stop PgBak Web UI
echo "Stopping PgBak Web UI..."
pkill -f "python web.py"
echo "Done."
