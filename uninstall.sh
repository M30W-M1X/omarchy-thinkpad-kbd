#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ID="thinkpad.kbd"
PLUGIN_DST="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
BIN_DST="$HOME/.local/bin/omarchy-thinkpad-kbd"
SERVICE_DST="$HOME/.config/systemd/user/omarchy-thinkpad-kbd.service"
HOOKS_JSON="$HOME/.gemini/config/hooks.json"

echo "==> Disabling Omarchy bar plugin..."
omarchy plugin disable "$PLUGIN_ID" >/dev/null 2>&1 || true
rm -rf "$PLUGIN_DST"
if command -v omarchy-shell >/dev/null 2>&1; then
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
fi

echo "==> Stopping and removing systemd user service..."
systemctl --user disable --now omarchy-thinkpad-kbd.service >/dev/null 2>&1 || true
rm -f "$SERVICE_DST"
systemctl --user daemon-reload >/dev/null 2>&1 || true

echo "==> Removing CLI symlink..."
rm -f "$BIN_DST"

echo "==> Removing 'thinkpad-kbd' hook from $HOOKS_JSON..."
if [[ -f "$HOOKS_JSON" ]]; then
  python3 - "$HOOKS_JSON" <<'PY'
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
if isinstance(data, dict) and "thinkpad-kbd" in data:
    del data["thinkpad-kbd"]
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
fi

echo "==> Uninstalled omarchy-thinkpad-kbd."
