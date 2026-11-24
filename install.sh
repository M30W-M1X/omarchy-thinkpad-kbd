#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="thinkpad.kbd"
PLUGIN_SRC="$REPO_DIR/omarchy-plugin"
PLUGIN_DST="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
BIN_DST="$HOME/.local/bin/omarchy-thinkpad-kbd"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_DST="$SYSTEMD_DIR/omarchy-thinkpad-kbd.service"
HOOKS_JSON="$HOME/.gemini/config/hooks.json"
HOOK_CMD="$REPO_DIR/hooks/agy-hook.py"

echo "==> Validating Omarchy plugin manifest..."
omarchy plugin validate "$PLUGIN_SRC"

echo "==> Setting executable permissions..."
chmod +x "$REPO_DIR/daemon/thinkpad_kbd_daemon.py" \
  "$REPO_DIR/hooks/agy-hook.py" \
  "$REPO_DIR/cli/omarchy-thinkpad-kbd" \
  "$REPO_DIR/install.sh" \
  "$REPO_DIR/uninstall.sh"

echo "==> Installing CLI to $BIN_DST..."
mkdir -p "$HOME/.local/bin"
ln -sfn "$REPO_DIR/cli/omarchy-thinkpad-kbd" "$BIN_DST"

echo "==> Installing Omarchy bar plugin to $PLUGIN_DST (copy, no symlinks)..."
mkdir -p "$HOME/.config/omarchy/plugins"
rm -rf "$PLUGIN_DST"
cp -r "$PLUGIN_SRC" "$PLUGIN_DST"
omarchy plugin validate "$PLUGIN_DST"

echo "==> Installing systemd user service..."
mkdir -p "$SYSTEMD_DIR"
sed "s|%h/Projects/omarchy-thinkpad-kbd|$REPO_DIR|g" \
  "$REPO_DIR/systemd/omarchy-thinkpad-kbd.service" > "$SERVICE_DST"

systemctl --user daemon-reload
systemctl --user enable --now omarchy-thinkpad-kbd.service

echo "==> Registering Antigravity (AGY) lifecycle hook in $HOOKS_JSON..."
python3 - "$HOOKS_JSON" "$HOOK_CMD" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

hooks_path = Path(sys.argv[1])
hook_cmd = sys.argv[2]

hooks_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if hooks_path.exists():
    raw = hooks_path.read_text(encoding="utf-8").strip()
    if raw:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise SystemExit(f"Expected JSON object in {hooks_path}")

handler = {"type": "command", "command": f"python3 '{hook_cmd}'", "timeout": 5}
data["thinkpad-kbd"] = {
    "enabled": True,
    "SessionStart": [handler],
    "PreInvocation": [handler],
    "PostToolUse": [
        {
            "matcher": "*",
            "hooks": [handler],
        }
    ],
    "Stop": [handler],
}

fd, tmp = tempfile.mkstemp(prefix=".hooks-", dir=str(hooks_path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, hooks_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PY

echo "==> Enabling Omarchy bar plugin ($PLUGIN_ID)..."
if command -v omarchy-shell >/dev/null 2>&1; then
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
  omarchy plugin enable "$PLUGIN_ID" --section right || true
fi

echo "==> Done! Current status:"
"$BIN_DST" status || true
