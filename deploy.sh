#!/usr/bin/env bash
# Laptop-side deploy: pull latest main, rebuild, restart. Run manually via SSH --
# intentionally not on an automatic timer, since this box holds decrypted
# credentials in memory and shouldn't pull unreviewed code unattended.
set -euo pipefail
cd "$(dirname "$0")"

git pull --ff-only origin main
docker compose up -d --build
docker image prune -f
