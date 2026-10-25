#!/usr/bin/env bash
set -Eeuo pipefail

case "${OPENSMS_SAAS_ENABLED:-0}" in
  1|true|TRUE|yes|YES|on|ON)
    alembic -c /app/opensms_gateway/saas/migrations/alembic.ini upgrade head
    ;;
esac

exec uvicorn run:app --host 0.0.0.0 --port 8080
