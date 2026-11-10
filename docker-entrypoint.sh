#!/bin/sh
set -e

echo "[KrishiVaani] Starting container entrypoint..."

# Ensure persistent volume data directory structure exists
mkdir -p /app/data/pjtau/raw_pdfs \
         /app/data/tgdps/raw_pdfs \
         /app/data/twilio_media

# 1. Initialize SQLite database from approved seed if not present on volume
if [ ! -f /app/data/krishivaani.db ] || [ ! -s /app/data/krishivaani.db ]; then
    echo "[KrishiVaani] Persistent database not found at /app/data/krishivaani.db."
    if [ -f /app/data_seed/krishivaani.db ]; then
        echo "[KrishiVaani] Initializing database from approved seed (/app/data_seed/krishivaani.db)..."
        cp /app/data_seed/krishivaani.db /app/data/krishivaani.db
        echo "[KrishiVaani] Database initialized successfully."
    else
        echo "[KrishiVaani] Warning: No seed database found at /app/data_seed/krishivaani.db."
    fi
else
    echo "[KrishiVaani] Existing persistent database found at /app/data/krishivaani.db. Preserving data."
fi

# 2. Seed approved raw PDFs if not present on volume
if [ -d /app/data_seed/pjtau/raw_pdfs ]; then
    cp -n /app/data_seed/pjtau/raw_pdfs/* /app/data/pjtau/raw_pdfs/ 2>/dev/null || true
fi
if [ -d /app/data_seed/tgdps/raw_pdfs ]; then
    cp -n /app/data_seed/tgdps/raw_pdfs/* /app/data/tgdps/raw_pdfs/ 2>/dev/null || true
fi

echo "[KrishiVaani] Volume initialization complete. Executing command: $@"
exec "$@"

