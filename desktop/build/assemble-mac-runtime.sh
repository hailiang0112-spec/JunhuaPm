#!/bin/bash
# Bundle a relocatable CPython and the Django app for the Mac desktop shell.
# Must run on Apple Silicon macOS: the interpreter shipped inside the .app is arm64.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DEST="$ROOT/desktop/payload"
CACHE="$ROOT/desktop/build/cache"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18%2B20261026-aarch64-apple-darwin-install_only.tar.gz"
PY_SHA="e5af2fde6a937a0e0c795a0c595c4efb70578d57463a2657c819992b9b9acbac"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "assemble-mac-runtime.sh 只能在 Apple Silicon（arm64）的 macOS 上运行。" >&2
  exit 1
fi
if [ ! -f "$ROOT/app/frontend/dist/index.html" ]; then
  echo "缺少 app/frontend/dist。请先在 app/frontend 执行 npm ci && npm run build。" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST" "$CACHE"
TGZ="$CACHE/cpython-3.13.18-aarch64-apple-darwin-install_only.tar.gz"
if [ ! -f "$TGZ" ]; then
  curl -fL --retry 3 --retry-delay 2 -o "$TGZ" "$PY_URL"
fi
echo "$PY_SHA  $TGZ" | shasum -a 256 -c -
tar -xzf "$TGZ" -C "$DEST"
mv "$DEST/python" "$DEST/runtime"
xattr -cr "$DEST/runtime" || true

PY="$DEST/runtime/bin/python3"
"$PY" -m ensurepip --upgrade
"$PY" -m pip install --disable-pip-version-check -r "$ROOT/desktop/requirements.txt"

mkdir -p "$DEST/backend" "$DEST/frontend"
rsync -a \
  --exclude '__pycache__' \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude 'staticfiles' \
  --exclude 'wheelhouse' \
  --exclude '.pytest_cache' \
  --exclude 'perf' \
  "$ROOT/app/backend/" "$DEST/backend/"
rsync -a "$ROOT/app/frontend/dist/" "$DEST/frontend/"

"$PY" -c "import django,rest_framework,PIL,pypdfium2,argon2,openpyxl,xlsxwriter; print('runtime', django.get_version())"
echo "payload ready at $DEST"
