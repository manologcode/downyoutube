#!/bin/sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/downloads}"

set -- python /app/web.py

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DOWNLOAD_DIR"
    chown "$PUID:$PGID" "$DOWNLOAD_DIR" 2>/dev/null || true
    exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
