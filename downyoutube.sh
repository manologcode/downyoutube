#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p downloads

exec env PUID="$(id -u)" PGID="$(id -g)" \
    docker compose up -d --build web
