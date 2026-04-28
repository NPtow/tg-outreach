#!/bin/bash

set -e

mkdir -p /app/api/storage
chown -R 1001:1001 /app/api/storage || true

exec /bin/bash /entrypoint.sh "$@"
