#!/bin/bash
# Doble clic en macOS: levanta Hangar en http://localhost:8000 con Docker Desktop.
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then
  osascript -e 'display dialog "Falta Docker Desktop. Descárgalo de docker.com/products/docker-desktop, ábrelo y vuelve a ejecutar este archivo." buttons {"Entendido"} with title "Hangar"'
  exit 1
fi
( sleep 25 && open "http://localhost:8000" ) &
docker compose -f docker-compose.local.yml up --build
