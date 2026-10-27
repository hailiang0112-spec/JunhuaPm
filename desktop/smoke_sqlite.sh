#!/bin/bash
# Prove the desktop runtime migrates SQLite, seeds demo accounts, and serves the UI.
# Does not build the Mac .app (that needs an Apple Silicon runner).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$ROOT/app/frontend/dist/index.html"
if [ ! -f "$DIST" ]; then
  echo "缺少前端构建产物 app/frontend/dist。请先 npm run build。" >&2
  exit 1
fi

PY="${PYTHON:-python3}"
DATA=$(mktemp -d)
LOG="$DATA/server.log"
COOKIE="$DATA/cookies.txt"
PID=""

cleanup() {
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$DATA"
}
trap cleanup EXIT

export JH_DATA_DIR="$DATA/support"
export JH_FRONTEND_DIST="$ROOT/app/frontend/dist"
export JH_DESKTOP=1
export PYTHONPATH="$ROOT/app/backend"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

"$PY" -m jh.desktop_serve >"$LOG" 2>&1 &
PID=$!

PORT=""
for _ in $(seq 1 240); do
  if grep -q '^JH_FAIL' "$LOG"; then
    echo "backend failed" >&2
    cat "$LOG" >&2
    exit 1
  fi
  PORT=$(grep -E '^JH_READY [0-9]+' "$LOG" | awk 'END { print $2 }' || true)
  if [ -n "${PORT:-}" ]; then
    break
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "backend exited before ready" >&2
    cat "$LOG" >&2
    exit 1
  fi
  sleep 1
done
if [ -z "${PORT:-}" ]; then
  echo "timed out waiting for JH_READY" >&2
  cat "$LOG" >&2
  exit 1
fi
echo "desktop backend ready on 127.0.0.1:$PORT"

BASE="http://127.0.0.1:$PORT"
curl -fsS -c "$COOKIE" "$BASE/api/auth/csrf" | grep -q '"ok"'
TOKEN=$(awk '$6 == "csrftoken" { print $7 }' "$COOKIE")
if [ -z "$TOKEN" ]; then
  echo "missing csrftoken" >&2
  exit 1
fi
LOGIN=$(curl -fsS -c "$COOKIE" -b "$COOKIE" \
  -H "X-CSRFToken: $TOKEN" -H "Content-Type: application/json" \
  -H "Origin: $BASE" -H "Referer: $BASE/" \
  -d '{"phone":"13800000004","password":"Jh123456"}' \
  "$BASE/api/auth/login")
printf '%s' "$LOGIN" | grep -q '张工'
PROJECT=$(printf '%s' "$LOGIN" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["projects"][0]["id"])')
curl -fsS -b "$COOKIE" "$BASE/api/me" | grep -q '张工'
curl -fsS -b "$COOKIE" "$BASE/api/projects/$PROJECT/checkpoints?page=1" | grep -q '"items"'
curl -fsS "$BASE/" | grep -q 'id="root"'
curl -fsS -o /dev/null -w '%{http_code}' "$BASE/login" | grep -q '200'
ASSET=$(grep -oE '/assets/index-[^"]+\.js' "$DIST" | head -1)
CODE=$(curl -fsS -o /dev/null -w '%{http_code}' "$BASE$ASSET")
test "$CODE" = "200"
# Hashed bundles must not fall through to index.html.
curl -fsS -D - -o /dev/null "$BASE$ASSET" | grep -i '^content-type:' | grep -iq 'javascript'
echo "SMOKE_OK project=$PROJECT asset=$ASSET"
