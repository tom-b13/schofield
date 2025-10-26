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

USE_EPHEMERAL_DB=${USE_EPHEMERAL_DB:-0}
POSTGRES_IMAGE=${POSTGRES_IMAGE:-postgres:16}
PGUSER=${PGUSER:-postgres}
PGPASSWORD=${PGPASSWORD:-postgres}
PGDATABASE=${PGDATABASE:-integration_tests}
DB_HOST=127.0.0.1
DB_PORT=""
BE_DB_CONT=""
BE_PID=""
BE_SRV_LOG=""
SVC_FILE=""

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
}

finalize() {
  status=$?
  set +e
  cleanup_services || true
  SERVER_LOG="${BE_SRV_LOG:-}"
  if [[ -z "$SERVER_LOG" ]]; then
    SERVER_LOG=$(ls -1t "$OUT_ROOT"/server_integration_*.log 2>/dev/null | head -n1)
  fi
  if [[ -z "$SERVER_LOG" && -f "$OUT_ROOT/db_${STAMP}.log" ]]; then
    SERVER_LOG="$OUT_ROOT/db_${STAMP}.log"
  fi
  if [[ -n "$SERVER_LOG" ]]; then
    printf '{"integration_test_logs":"%s"}\n' "$SERVER_LOG"
  else
    printf '{"integration_test_logs":""}\n'
  fi
  # Cleanup temp files
  if [[ -n "${SVC_FILE:-}" && -f "$SVC_FILE" ]]; then
    rm -f "$SVC_FILE" || true
  fi
  exit $status
}
trap finalize EXIT INT TERM

# Start backend services (uvicorn + optional ephemeral DB) using the shared starter
export USE_EPHEMERAL_DB POSTGRES_IMAGE PGUSER PGPASSWORD PGDATABASE
SVC_FILE=$(mktemp -t be_svc_json_XXXXXX)
bash "$ROOT_DIR/scripts/run-be-services.sh" > "$SVC_FILE" || true
if [[ -s "$SVC_FILE" ]]; then
  echo "[be-services] $(cat "$SVC_FILE")"
fi
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
  fi
else
  echo "[run-integration] WARN: backend services did not return test_base_url; falling back to no-server mode" >&2
  if [[ -s "$SVC_FILE" ]]; then
    echo "[run-integration][debug] raw_services_json=$(cat "$SVC_FILE")" >&2
  else
    echo "[run-integration][debug] services_json_file_empty path=$SVC_FILE" >&2
  fi
  # Provide minimal env for Behave to proceed without server lifecycle
  export SKIP_INTEGRATION_ENV_HOOK=1
  export TEST_BASE_URL="${TEST_BASE_URL:-http://127.0.0.1:0}"
  export TEST_DATABASE_URL="${TEST_DATABASE_URL:-sqlite:///:memory:}"
fi

cd "$ROOT_DIR"
FEATURES_DIR="tests/integration/features"
if [[ ! -d "$FEATURES_DIR" ]]; then
  echo "[run-integration] ERROR: features directory not found at $ROOT_DIR/$FEATURES_DIR" >&2
  exit 2
fi
set +e
./.venv/bin/python -m behave "$FEATURES_DIR" "$@"
STATUS=$?
set -e
exit ${STATUS:-0}
