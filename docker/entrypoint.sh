#!/bin/sh
# Canonical one-image-many-roles entrypoint. Role = first arg or $ENOS_ROLE.
set -e

ROLE="${1:-${ENOS_ROLE:-api}}"

case "$ROLE" in
  api)
    alembic upgrade head
    exec uvicorn enos.api.app:app --host 0.0.0.0 --port 8000
    ;;
  mcp)
    exec uvicorn enos.mcp.app:app --host 0.0.0.0 --port 8001
    ;;
  worker)
    exec celery -A enos.worker.app:celery_app worker --beat --loglevel INFO
    ;;
  *)
    echo "Unknown role: $ROLE (expected api | mcp | worker)" >&2
    exit 64
    ;;
esac
