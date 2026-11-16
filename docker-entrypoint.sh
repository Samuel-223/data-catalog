#!/usr/bin/env bash
set -euo pipefail

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WORKERS:-1}"
