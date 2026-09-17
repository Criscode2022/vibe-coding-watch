#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
PLIST_SRC="$ROOT/macos/com.vibeos.bridge.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.vibeos.bridge.plist"
mkdir -p "$ROOT/data" "$HOME/Library/LaunchAgents"

if [[ ! -x "$PY" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
fi

python3 - <<PY
from pathlib import Path
root = Path(r"$ROOT")
src = Path(r"$PLIST_SRC")
dst = Path(r"$PLIST_DST")
text = src.read_text()
text = text.replace("VIBEOS_ROOT", str(root))
text = text.replace("VIBEOS_PYTHON", str(root / ".venv/bin/python"))
dst.write_text(text)
print("wrote", dst)
PY

launchctl bootout "gui/$UID/com.vibeos.bridge" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_DST"
launchctl enable "gui/$UID/com.vibeos.bridge" 2>/dev/null || true
launchctl kickstart -k "gui/$UID/com.vibeos.bridge"
echo "VibeOS is running on this Mac Mini at http://0.0.0.0:7733/"
echo "On iPhone: install the VibeOS app, pair the ZTE watch as a Bluetooth headset,"
echo "and set the bridge URL to this Mac's Tailscale IP, port 7733."
