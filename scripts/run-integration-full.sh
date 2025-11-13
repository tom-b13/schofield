#!/usr/bin/env bash
set -euo pipefail

# Resolve project root robustly relative to this script (handles symlinks and PATH invocation)
SOURCE=${BASH_SOURCE[0]:-$0}
while [ -h "$SOURCE" ]; do
  DIR=$(cd -P "$(dirname "$SOURCE")" && pwd)
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR=$(cd -P "$(dirname "$SOURCE")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
OUT_ROOT="$ROOT_DIR/tmp"
mkdir -p "$OUT_ROOT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

USE_EPHEMERAL_DB=${USE_EPHEMERAL_DB:-1}
POSTGRES_IMAGE=${POSTGRES_IMAGE:-postgres:16}
PGUSER=${PGUSER:-postgres}
PGPASSWORD=${PGPASSWORD:-postgres}
PGDATABASE=${PGDATABASE:-integration_tests}
INTEGRATION_TIMEOUT_SEC=${INTEGRATION_TIMEOUT_SEC:-300}
HEARTBEAT_INTERVAL_SEC=${HEARTBEAT_INTERVAL_SEC:-5}
DB_HOST=127.0.0.1
DB_PORT=""
BE_DB_CONT=""
BE_PID=""
BE_SRV_LOG=""
SVC_FILE=""
HB_PID=""

cleanup_services() {
  # Stop uvicorn
  if [[ -n "${BE_PID:-}" ]]; then
    kill "$BE_PID" 2>/dev/null || true
  fi
  # Capture DB logs and tear down ephemeral DB if started by be-services
  if [[ -n "${BE_DB_CONT:-}" ]]; then
    docker logs "$BE_DB_CONT" > "$OUT_ROOT/db_${STAMP}.log" 2>&1 || true
    docker rm -f "$BE_DB_CONT" >/dev/null 2>&1 || true
  fi
  # Stop heartbeat loop if running
  if [[ -n "${HB_PID:-}" ]]; then
    kill "$HB_PID" 2>/dev/null || true
  fi
}

finalize() {
  status=$?
  set +e
  cleanup_services || true
  # Resolve server and DB logs captured during the run
  SERVER_LOG="${BE_SRV_LOG:-}"
  if [[ -z "$SERVER_LOG" ]]; then
    SERVER_LOG=$(ls -1t "$OUT_ROOT"/server_integration_*.log 2>/dev/null | head -n1)
  fi
  DB_LOG=""
  if [[ -f "$OUT_ROOT/db_${STAMP}.log" ]]; then
    DB_LOG="$OUT_ROOT/db_${STAMP}.log"
  fi

  # Build a tarball with available logs in tmp using the same timestamp
  TAR_PATH="$OUT_ROOT/integration_logs_${STAMP}.tar.gz"
  files_to_pack=()
  [[ -n "$SERVER_LOG" && -f "$SERVER_LOG" ]] && files_to_pack+=("$SERVER_LOG")
  [[ -n "$DB_LOG" && -f "$DB_LOG" ]] && files_to_pack+=("$DB_LOG")

  # Ensure we always have at least one file to pack
  if [[ ${#files_to_pack[@]} -eq 0 ]]; then
    NOTE_FILE="$OUT_ROOT/integration_no_logs_${STAMP}.txt"
    echo "No logs were captured during this run." > "$NOTE_FILE" 2>/dev/null || true
    files_to_pack+=("$NOTE_FILE")
  fi

  # Normalize to basenames inside archive (store without absolute paths)
  tmp_list=()
  for f in "${files_to_pack[@]}"; do
    cp -f "$f" "$OUT_ROOT/$(basename "$f")" >/dev/null 2>&1 || true
    tmp_list+=("$(basename "$f")")
  done
  tar -C "$OUT_ROOT" -czf "$TAR_PATH" "${tmp_list[@]}" 2>/dev/null || true

  RAW_OUTPUT_PATH="$OUT_ROOT/raw_integration_test_output_integration_${STAMP}.txt"
  if [[ -f "$TAR_PATH" ]]; then
    # Include bundle and raw_output to satisfy upstream harness schema and avoid fallbacks
    printf '{"integration_test_logs":"%s","bundle":"%s","raw_output":"%s","status":%d}\n' \
      "$TAR_PATH" "$TAR_PATH" "$RAW_OUTPUT_PATH" ${status:-0}
  else
    # As a last resort, still emit a JSON without pointing to raw output for logs
    printf '{"integration_test_logs":"","bundle":"","raw_output":"%s","status":%d}\n' \
      "$RAW_OUTPUT_PATH" ${status:-0}
  fi
  # Cleanup temp files
  if [[ -n "${SVC_FILE:-}" && -f "$SVC_FILE" ]]; then
    rm -f "$SVC_FILE" || true
  fi
  exit $status
}
# Ensure finalize runs on common termination signals (can't trap SIGKILL)
trap finalize EXIT INT TERM HUP QUIT

# Start backend services (uvicorn + optional ephemeral DB) using the shared starter
export USE_EPHEMERAL_DB POSTGRES_IMAGE PGUSER PGPASSWORD PGDATABASE
SVC_FILE=$(mktemp -t be_svc_json_XXXXXX)
set +e
bash "$ROOT_DIR/scripts/run-be-services.sh" > "$SVC_FILE"
SVC_STATUS=$?
set -e
if [[ $SVC_STATUS -ne 0 || ! -s "$SVC_FILE" ]]; then
  echo "[run-integration] ERROR: backend services failed to start (status=$SVC_STATUS, svc_file_size=$(stat -c%s "$SVC_FILE" 2>/dev/null || echo 0))" >&2
  # Fail early; finalize trap will package any available logs
  exit 10
fi
# Send service discovery to stderr to avoid polluting stdout summary
echo "[be-services] $(cat "$SVC_FILE")" >&2
BE_URL=$(python3 - "$SVC_FILE" <<'PY'
import json,sys,re
p=sys.argv[1] if len(sys.argv)>1 else ''
data=''
try:
    with open(p,'r',encoding='utf-8',errors='ignore') as f:
        data=f.read()
except Exception:
    data=''
val=''
if data:
    try:
        val=json.loads(data).get('test_base_url','') or ''
    except Exception:
        m=re.search(r'"test_base_url"\s*:\s*"([^"]+)"', data)
        val=m.group(1) if m else ''
print(val)
PY
)
BE_DB_CONT=$(python3 - "$SVC_FILE" <<'PY'
import json,sys
p=sys.argv[1] if len(sys.argv)>1 else ''
try:
    s=open(p,'r',encoding='utf-8',errors='ignore').read()
    print(json.loads(s).get('db_container','') if s else '')
except Exception:
    print('')
PY
)
BE_PID=$(python3 - "$SVC_FILE" <<'PY'
import json,sys
p=sys.argv[1] if len(sys.argv)>1 else ''
try:
    s=open(p,'r',encoding='utf-8',errors='ignore').read()
    print(json.loads(s).get('server_pid','') if s else '')
except Exception:
    print('')
PY
)
BE_SRV_LOG=$(python3 - "$SVC_FILE" <<'PY'
import json,sys
p=sys.argv[1] if len(sys.argv)>1 else ''
try:
    s=open(p,'r',encoding='utf-8',errors='ignore').read()
    print(json.loads(s).get('server_log','') if s else '')
except Exception:
    print('')
PY
)
BE_DB_PORT=$(python3 - "$SVC_FILE" <<'PY'
import json,sys
p=sys.argv[1] if len(sys.argv)>1 else ''
try:
    s=open(p,'r',encoding='utf-8',errors='ignore').read()
    print(json.loads(s).get('db_port','') if s else '')
except Exception:
    print('')
PY
)

if [[ -n "$BE_URL" ]]; then
  export TEST_BASE_URL="$BE_URL"
  export E2E_SKIP_SERVER=1
  echo "[run-integration] BE_URL=$BE_URL BE_PID=$BE_PID BE_DB_CONT=$BE_DB_CONT LOG=$BE_SRV_LOG DB_PORT=${BE_DB_PORT}"
  if [[ -n "${BE_DB_PORT:-}" ]]; then
    export TEST_DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@127.0.0.1:${BE_DB_PORT}/${PGDATABASE}"
    # Force DATABASE_URL to match the ephemeral DB for the test process
    export DATABASE_URL="$TEST_DATABASE_URL"
    echo "[run-integration] TEST_DATABASE_URL set (host=127.0.0.1 port=${BE_DB_PORT})"
  else
    # Avoid leaking a stale DATABASE_URL from the environment; fall back to SQLite for this run
    export TEST_DATABASE_URL="${TEST_DATABASE_URL:-sqlite:///:memory:}"
    export DATABASE_URL="$TEST_DATABASE_URL"
    echo "[run-integration] No ephemeral DB detected; using in-memory SQLite for tests"
  fi
  # Wait for backend TCP and health readiness (align FE orchestration)
  BE_HOST_PORT="${BE_URL#*://}"
  BE_HOST="${BE_HOST_PORT%%:*}"
  BE_PORT_READY="${BE_HOST_PORT##*:}"
  if command -v npx >/dev/null 2>&1; then
    npx --yes wait-on -t 30000 -i 500 "tcp:${BE_HOST}:${BE_PORT_READY}" >/dev/null 2>&1 || true
    npx --yes wait-on -t 30000 -i 1000 "${BE_URL}/health" >/dev/null 2>&1 || true
  else
    # Fallback: brief curl poll
    for i in {1..200}; do
      curl -fsS "${BE_URL}/health" >/dev/null 2>&1 && break || true
      sleep 0.2
    done
  fi
else
  echo "[run-integration] ERROR: backend services did not return test_base_url; aborting integration run" >&2
  echo "[run-integration][debug] raw_services_json=$(cat "$SVC_FILE" 2>/dev/null || true)" >&2
  exit 11
fi

cd "$ROOT_DIR"
FEATURES_DIR="tests/integration/features"
if [[ ! -d "$FEATURES_DIR" ]]; then
  echo "[run-integration] ERROR: features directory not found at $ROOT_DIR/$FEATURES_DIR" >&2
  exit 2
fi
set +e
# Start a light heartbeat to avoid external quiet timeouts (stderr only)
(
  while true; do
    sleep "${HEARTBEAT_INTERVAL_SEC}"
    # Send heartbeat to stdout so external harnesses see activity and avoid quiet timeouts
    echo "[run-integration] heartbeat $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  done
) &
HB_PID=$!

# Run behave with a graceful timeout to ensure finalize trap executes
if command -v timeout >/dev/null 2>&1; then
  timeout --preserve-status -k 10 "${INTEGRATION_TIMEOUT_SEC}" ./.venv/bin/python -m behave "$FEATURES_DIR" "$@"
else
  ./.venv/bin/python -m behave "$FEATURES_DIR" "$@"
fi
STATUS=$?
set -e
exit ${STATUS:-0}
