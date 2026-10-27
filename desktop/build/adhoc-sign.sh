#!/bin/bash
# Ad-hoc sign a JunhuaPm.app so Apple Silicon will launch it.
# This is not a Developer ID signature. Gatekeeper still asks the user to confirm
# the first open of a downloaded copy.
set -euo pipefail

APP="${1:-}"
if [ -z "$APP" ] || [ ! -d "$APP" ]; then
  echo "usage: adhoc-sign.sh JunhuaPm.app" >&2
  exit 1
fi

xattr -cr "$APP" || true

# Sign inner Mach-O files first (bundled CPython and its extensions), then the app.
find "$APP" -type f -print0 | while IFS= read -r -d '' file; do
  if file -b "$file" | grep -q 'Mach-O'; then
    codesign --force --sign - "$file"
  fi
done
codesign --force --sign - "$APP"
codesign --verify --verbose=2 "$APP"
echo "ad-hoc signed $APP"
