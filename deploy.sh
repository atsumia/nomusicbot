#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
test -f deployment.env
docker compose -p nomusicbot config --quiet
docker compose -p nomusicbot up --build -d
docker compose -p nomusicbot ps
