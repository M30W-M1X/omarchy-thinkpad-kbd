#!/usr/bin/env python3
"""Antigravity (AGY) lifecycle hook for Omarchy ThinkPad Keyboard Backlight.

Reads hook JSON payload from stdin, maps the event to a keyboard lighting
state, notifies the local daemon over its Unix socket with a short timeout,
and always returns `{}` on stdout so it never blocks or breaks AGY.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Optional, Tuple

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
SOCKET_PATH = Path(
    os.environ.get("THINKPAD_KBD_SOCKET") or (RUNTIME_DIR / "omarchy-thinkpad-kbd.sock")
)

COMMAND_TOOLS = {
    "run_command",
    "manage_task",
    "schedule",
}
EDIT_TOOLS = {
    "edit_file",
    "write_file",
    "multi_replace_file_content",
    "replace_file_content",
    "write_to_file",
}
READ_TOOLS = {
    "read_file",
    "view_file",
    "view_file_outline",
    "view_code_item",
    "grep_search",
    "find_by_name",
    "list_dir",
    "search_web",
    "read_url_content",
}
AGENT_TOOLS = {
    "invoke_subagent",
    "define_subagent",
    "manage_subagents",
    "send_message",
    "swarm",
    "run_workflow",
}


def map_hook_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Map an AGY hook payload to (daemon_state, detail)."""
    event = str(payload.get("hookEventName") or "").strip()

    if event == "SessionStart":
        return ("session_start", "session")

    if event == "PreInvocation":
        return ("thinking", "thinking")

    if event == "PostToolUse":
        err = str(payload.get("error") or "").strip()
        tool_call = payload.get("toolCall")
        tool_name = ""
        if isinstance(tool_call, dict):
            tool_name = str(tool_call.get("name") or "").strip().lower()
        if err:
            return ("error", tool_name or "error")
        if tool_name in COMMAND_TOOLS:
            return ("tool_command", tool_name)
        if tool_name in EDIT_TOOLS:
            return ("tool_edit", tool_name)
        if tool_name in READ_TOOLS:
            return ("tool_read", tool_name)
        if tool_name in AGENT_TOOLS:
            return ("tool_agent", tool_name)
        return ("thinking", tool_name or "tool")

    if event == "Stop":
        err = str(payload.get("error") or "").strip()
        reason = str(payload.get("terminationReason") or "").strip().upper()
        fully_idle = payload.get("fullyIdle")
        if err or reason == "ERROR":
            return ("error", reason.lower() or "error")
        if reason in {
            "USER_CANCELED",
            "MAX_INVOCATIONS",
            "MAX_FORCED_INVOCATIONS",
            "MAX_TOKEN_BUDGET_EXCEEDED",
            "TERMINAL_CUSTOM_HOOK",
        }:
            return ("attention", reason.lower())
        if fully_idle is False:
            return ("thinking", "background")
        return ("complete", reason.lower() or "done")

    return None


def send_event(state: str, detail: str, socket_path: Path = SOCKET_PATH) -> None:
    if not socket_path.exists():
        return
    req = {"cmd": "event", "event": state, "detail": detail}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.15)
            client.connect(str(socket_path))
            client.sendall((json.dumps(req) + "\n").encode("utf-8"))
            try:
                client.recv(1024)
            except Exception:
                pass
    except Exception:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
            if isinstance(payload, dict):
                mapped = map_hook_payload(payload)
                if mapped is not None:
                    send_event(mapped[0], mapped[1])
    except Exception:
        pass
    sys.stdout.write("{}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
