#!/usr/bin/env python3
"""Unit and integration tests for omarchy-thinkpad-kbd."""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


daemon_mod = load_module("thinkpad_kbd_daemon", ROOT / "daemon" / "thinkpad_kbd_daemon.py")
hook_mod = load_module("agy_hook", ROOT / "hooks" / "agy-hook.py")


class TestHookMapping(unittest.TestCase):
    def test_session_start(self):
        self.assertEqual(
            hook_mod.map_hook_payload({"hookEventName": "SessionStart"}),
            ("session_start", "session"),
        )

    def test_pre_invocation(self):
        self.assertEqual(
            hook_mod.map_hook_payload({"hookEventName": "PreInvocation"}),
            ("thinking", "thinking"),
        )

    def test_post_tool_use_categories(self):
        cases = [
            ("run_command", "tool_command"),
            ("edit_file", "tool_edit"),
            ("write_file", "tool_edit"),
            ("read_file", "tool_read"),
            ("search_web", "tool_read"),
            ("invoke_subagent", "tool_agent"),
            ("swarm", "tool_agent"),
            ("unknown_tool", "thinking"),
        ]
        for tool, expected in cases:
            mapped = hook_mod.map_hook_payload(
                {"hookEventName": "PostToolUse", "toolCall": {"name": tool}}
            )
            self.assertEqual(mapped, (expected, tool))

    def test_post_tool_use_error_overrides(self):
        mapped = hook_mod.map_hook_payload(
            {
                "hookEventName": "PostToolUse",
                "toolCall": {"name": "run_command"},
                "error": "exit status 1",
            }
        )
        self.assertEqual(mapped, ("error", "run_command"))

    def test_stop_reasons(self):
        self.assertEqual(
            hook_mod.map_hook_payload(
                {"hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL", "fullyIdle": True}
            ),
            ("complete", "no_tool_call"),
        )
        self.assertEqual(
            hook_mod.map_hook_payload(
                {"hookEventName": "Stop", "terminationReason": "ERROR", "error": "boom"}
            ),
            ("error", "error"),
        )
        self.assertEqual(
            hook_mod.map_hook_payload(
                {"hookEventName": "Stop", "terminationReason": "USER_CANCELED"}
            ),
            ("attention", "user_canceled"),
        )
        self.assertEqual(
            hook_mod.map_hook_payload(
                {"hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL", "fullyIdle": False}
            ),
            ("thinking", "background"),
        )


class TestDaemonIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.sock = base / "test.sock"
        self.status = base / "status.json"
        self.config = base / "config.json"
        self.daemon = daemon_mod.ThinkPadKbdDaemon(
            socket_path=self.sock,
            status_path=self.status,
            config_path=self.config,
            dry_run=True,
        )
        self.daemon.hw.set_level(1, force=True)
        self.daemon.config.resting_level = 1
        self.thread = threading.Thread(target=self.daemon.run, daemon=True)
        self.thread.start()
        for _ in range(50):
            if self.sock.exists():
                break
            time.sleep(0.02)
        self.assertTrue(self.sock.exists(), "daemon socket did not come up")

    def tearDown(self):
        self.daemon.stop()
        self.thread.join(timeout=2.0)
        self.tmpdir.cleanup()

    def send(self, payload: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(str(self.sock))
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            raw = client.recv(4096).decode("utf-8").strip()
            return json.loads(raw)

    def test_status_and_level(self):
        st = self.send({"cmd": "status"})
        self.assertTrue(st["ok"])
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["mode"], "adaptive")

        st2 = self.send({"cmd": "set_level", "level": 2})
        self.assertEqual(st2["level"], 2)
        self.assertEqual(st2["resting_level"], 2)

    def test_event_animates_and_restores(self):
        self.send({"cmd": "set_level", "level": 1})
        st = self.send({"cmd": "event", "event": "thinking", "detail": "test"})
        self.assertTrue(st["active"])
        self.assertEqual(st["state"], "thinking")

        st_idle = self.send({"cmd": "event", "event": "idle"})
        self.assertFalse(st_idle["active"])
        self.assertEqual(st_idle["state"], "idle")
        self.assertEqual(st_idle["level"], 1)

    def test_one_shot_preview_returns_to_idle(self):
        self.send({"cmd": "set_level", "level": 1})
        st = self.send({"cmd": "preview", "state": "start"})
        self.assertEqual(st["state"], "session_start")
        # session_start takes ~0.94s total
        for _ in range(30):
            time.sleep(0.1)
            cur = self.send({"cmd": "status"})
            if cur["state"] == "idle":
                break
        self.assertEqual(cur["state"], "idle")
        self.assertEqual(cur["level"], 1)

    def test_disabled_ignores_events_but_allows_preview(self):
        self.send({"cmd": "set_enabled", "enabled": False})
        st = self.send({"cmd": "event", "event": "thinking"})
        self.assertEqual(st["state"], "idle")

        st_prev = self.send({"cmd": "preview", "state": "think", "duration": 0.6})
        self.assertEqual(st_prev["state"], "thinking")

    def test_cli_and_hook_subprocess(self):
        env = {"THINKPAD_KBD_SOCKET": str(self.sock), "PATH": "/usr/bin:/bin"}
        hook_proc = subprocess.run(
            ["python3", str(ROOT / "hooks" / "agy-hook.py")],
            input=json.dumps({"hookEventName": "PreInvocation"}),
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        self.assertEqual(hook_proc.stdout.strip(), "{}")

        cli_proc = subprocess.run(
            ["python3", str(ROOT / "cli" / "omarchy-thinkpad-kbd"), "status", "--json"],
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        data = json.loads(cli_proc.stdout)
        self.assertEqual(data["state"], "thinking")


if __name__ == "__main__":
    unittest.main()
