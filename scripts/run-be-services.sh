#!/usr/bin/env bash
set -euo pipefail

# Backend services starter: (optionally) start ephemeral Postgres and start uvicorn,
# then print a single JSON line with details and exit. No traps here — the caller
# (e.g., FE one-stop script) owns cleanup.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
OUT_ROOT="$ROOT_DIR/tmp"
mkdir -p "$OUT_ROOT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SERVER_LOG="$OUT_ROOT/server_integration_${STAMP}.log"

USE_EPHEMERAL_DB=${USE_EPHEMERAL_DB:-0}
POSTGRES_IMAGE=${POSTGRES_IMAGE:-postgres:16}
PGUSER=${PGUSER:-postgres}
PGPASSWORD=${PGPASSWORD:-postgres}
PGDATABASE=${PGDATABASE:-integration_tests}
DB_CONT=""
DB_HOST=127.0.0.1
DB_PORT=""

# Optional ephemeral DB
if [[ "$USE_EPHEMERAL_DB" == "1" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "[be-services] ERROR: docker not found but USE_EPHEMERAL_DB=1" >&2
    exit 3
  fi
  DB_CONT="schofield-be-services-${STAMP}"
  docker run -d --rm --name "$DB_CONT" \
    -e POSTGRES_USER="$PGUSER" \
    -e POSTGRES_PASSWORD="$PGPASSWORD" \
    -e POSTGRES_DB="$PGDATABASE" \
    --health-cmd="pg_isready -U $PGUSER" \
    --health-interval=1s \
    --health-timeout=5s \
    --health-retries=30 \
    -p 0:5432 "$POSTGRES_IMAGE" >/dev/null
  for i in {1..60}; do
    DB_PORT=$(docker port "$DB_CONT" 5432/tcp 2>/dev/null | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n1)
    [[ -n "$DB_PORT" ]] && break
    sleep 0.5
  done
  # Export discovered port for child processes/tests
  export DB_PORT
  # Wait for container health if available (with TCP fallback)
  for i in {1..60}; do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONT" 2>/dev/null || echo "unknown")
    if [[ "$status" == "healthy" ]]; then break; fi
    (echo > /dev/tcp/$DB_HOST/$DB_PORT) >/dev/null 2>&1 && break
    sleep 1
  done
  # Sanity: try connecting using TEST_DATABASE_URL until it works (stderr only)
  if command -v "$ROOT_DIR/.venv/bin/python" >/dev/null 2>&1; then
    for i in {1..30}; do
      "$ROOT_DIR/.venv/bin/python" - <<PY 1>/dev/null 2>>"$SERVER_LOG" && break || true
import os
import psycopg2
dsn=os.getenv('TEST_DATABASE_URL','')
if not dsn:
    raise SystemExit(1)
conn=psycopg2.connect(dsn)
conn.close()
PY
      sleep 1
    done
  fi
  export TEST_DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${DB_HOST}:${DB_PORT}/${PGDATABASE}"
  # Force DATABASE_URL to match the ephemeral DB to avoid mismatches with any pre-set value
  export DATABASE_URL="$TEST_DATABASE_URL"
fi

# Pick a free port for uvicorn
UV_PORT=$(python3 - <<'PY'
import socket
s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()
PY
)

# Install runtime dependencies if a requirements file is present (best-effort)
if [[ -f "$ROOT_DIR/requirements.txt" && -x "$ROOT_DIR/.venv/bin/pip" ]]; then
  "$ROOT_DIR/.venv/bin/pip" install -r "$ROOT_DIR/requirements.txt" >> "$SERVER_LOG" 2>&1 || true
fi

# Start uvicorn (ensure app is allowed to run migrations at startup)
export AUTO_APPLY_MIGRATIONS=${AUTO_APPLY_MIGRATIONS:-1}
cd "$ROOT_DIR"
UV_CMD=("$ROOT_DIR/.venv/bin/python" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port "$UV_PORT" --log-level info)
"${UV_CMD[@]}" > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Wait readiness (HTTP)
BASE_URL="http://127.0.0.1:${UV_PORT}"
for i in {1..300}; do
  if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then break; fi
  sleep 0.1
done

# If server is not ready after waiting, emit a helpful error and exit non-zero
if ! curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  echo "[be-services] ERROR: server not reachable at $BASE_URL/health after wait" >&2
  echo "[be-services] tail server log:" >&2
  tail -n 120 "$SERVER_LOG" >&2 || true
  exit 6
fi

# Emit single JSON line with details
printf '{"test_base_url":"%s","db_container":"%s","db_port":"%s","server_pid":"%s","server_log":"%s"}\n' \
  "$BASE_URL" "$DB_CONT" "$DB_PORT" "$SERVER_PID" "$SERVER_LOG"
