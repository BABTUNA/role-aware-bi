#!/usr/bin/env bash
# Usage: bash render.sh <name> <width,height>   renders <name>.html to <name>.png at 2x with headless Chrome.
set -euo pipefail
NAME=${1:-diagram}; SIZE=${2:-1560,760}
DIR="$(pwd)"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-sandbox --allow-file-access-from-files --virtual-time-budget=6000 \
  --force-device-scale-factor=2 --window-size="$SIZE" --screenshot="$DIR/$NAME.png" "file://$DIR/$NAME.html" >/dev/null 2>&1
echo "wrote $NAME.png"
