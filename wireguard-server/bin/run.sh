#!/bin/bash
set -e
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/..
cd "$DIR"

docker compose build
docker compose stop
docker compose up -d
echo "Logs: docker compose -f $DIR/docker-compose.yml logs -f"
