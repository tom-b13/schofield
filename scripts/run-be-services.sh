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

USE_EPHEMERAL_DB=${USE_EPHEMERAL_DB:-1}
POSTGRES_IMAGE=${POSTGRES_IMAGE:-postgres:16}
PGUSER=${PGUSER:-postgres}
PGPASSWORD=${PGPASSWORD:-postgres}
PGDATABASE=${PGDATABASE:-integration_tests}
PG_TMPFS_SIZE=${PG_TMPFS_SIZE:-512m}
DB_CONT=""
DB_HOST=127.0.0.1
DB_PORT=""

# Optional ephemeral DB (mirror FE orchestration closely)
if [[ "$USE_EPHEMERAL_DB" == "1" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "[be-services] ERROR: docker not found; set USE_EPHEMERAL_DB=0 or install docker" >&2
    exit 3
  fi
  DB_CONT="schofield-be-services-${STAMP}"
  echo "[be-services] starting ephemeral Postgres: $POSTGRES_IMAGE (container=$DB_CONT)" >&2
  # Start container and capture ID
  if ! DB_ID=$(docker run -d --name "$DB_CONT" \
    -e POSTGRES_USER="$PGUSER" \
    -e POSTGRES_PASSWORD="$PGPASSWORD" \
    -e POSTGRES_DB="$PGDATABASE" \
    --tmpfs "/var/lib/postgresql/data:rw,size=${PG_TMPFS_SIZE}" \
    -p 0:5432 "$POSTGRES_IMAGE" 2>>"$SERVER_LOG"); then
    echo "[be-services] ERROR: docker run failed; see server log for details" >&2
    exit 3
  fi
  # Background-follow container logs immediately to avoid losing early output
  DB_LOG_PATH="$OUT_ROOT/db_${STAMP}.log"
  (docker logs -f "$DB_CONT" > "$DB_LOG_PATH" 2>&1) &
  DB_LOG_PID=$!
  # Resolve mapped port
  for i in {1..30}; do
    DB_PORT=$(docker port "$DB_CONT" 5432/tcp 2>/dev/null | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n1)
    [[ -n "$DB_PORT" ]] && break
    sleep 0.5
  done
  if [[ -z "$DB_PORT" ]]; then
    echo "[be-services] ERROR: failed to discover mapped port for $DB_CONT" >&2
    # Capture DB container logs before cleanup
    docker logs "$DB_CONT" > "$OUT_ROOT/db_${STAMP}.log" 2>&1 || true
    docker rm -f "$DB_CONT" >/dev/null 2>&1 || true
    exit 4
  fi
  echo "[be-services] postgres listening on $DB_HOST:$DB_PORT" >&2
  # Wait for DB TCP ready via wait-on if available
  if command -v npx >/dev/null 2>&1; then
    npx --yes wait-on -t 30000 -i 500 "tcp:${DB_HOST}:${DB_PORT}" >/dev/null 2>&1 || true
  fi
  # Additionally, wait until pg_isready inside the container reports ready
  DB_READY=0
  for i in {1..60}; do
    if docker exec "$DB_CONT" pg_isready -U "$PGUSER" -h localhost -p 5432 >/dev/null 2>&1; then
      DB_READY=1
      break
    fi
    sleep 1
  done
  if [[ "$DB_READY" != "1" ]]; then
    echo "[be-services] ERROR: Postgres did not become ready in time (pg_isready failed)" >&2
    echo "[be-services] docker logs for $DB_CONT (last 120 lines):" >&2
    docker logs --tail 120 "$DB_CONT" >&2 || true
    # Ensure background follower is stopped
    kill "$DB_LOG_PID" 2>/dev/null || true
    docker rm -f "$DB_CONT" >/dev/null 2>&1 || true
    exit 5
  fi
  # DB is ready: stop the background log follower (we'll capture logs on cleanup later if needed)
  kill "$DB_LOG_PID" 2>/dev/null || true
  # Export DSN after readiness wait (align with FE)
  export TEST_DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${DB_HOST}:${DB_PORT}/${PGDATABASE}"
  export DATABASE_URL="${DATABASE_URL:-$TEST_DATABASE_URL}"
  export DB_PORT
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
# First wait for TCP if wait-on is present
if command -v npx >/dev/null 2>&1; then
  npx --yes wait-on -t 30000 -i 500 "tcp:127.0.0.1:${UV_PORT}" >/dev/null 2>&1 || true
fi
# Then poll /health
for i in {1..300}; do
  if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then break; fi
  sleep 0.1
done
if ! curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  echo "[be-services] ERROR: server not reachable at $BASE_URL/health after wait" >&2
  echo "[be-services] tail server log:" >&2
  tail -n 120 "$SERVER_LOG" >&2 || true
  exit 6
fi

# Emit single JSON line with details
printf '{"test_base_url":"%s","db_container":"%s","db_port":"%s","server_pid":"%s","server_log":"%s"}\n' \
  "$BASE_URL" "$DB_CONT" "$DB_PORT" "$SERVER_PID" "$SERVER_LOG"
