#!/usr/bin/env python3
"""Omarchy ThinkPad Keyboard Backlight Daemon.

Drives ThinkPad keyboard backlight (tpacpi::kbd_backlight, levels 0/1/2)
animations in response to Antigravity (AGY) lifecycle hook events, CLI
commands, and the Omarchy bar widget.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LED_NAME = "tpacpi::kbd_backlight"
LED_SYSFS = Path(f"/sys/class/leds/{LED_NAME}/brightness")
LED_MAX_SYSFS = Path(f"/sys/class/leds/{LED_NAME}/max_brightness")

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
SOCKET_PATH = Path(
    os.environ.get("THINKPAD_KBD_SOCKET") or (RUNTIME_DIR / "omarchy-thinkpad-kbd.sock")
)
STATUS_PATH = Path(
    os.environ.get("THINKPAD_KBD_STATUS")
    or (RUNTIME_DIR / "omarchy-thinkpad-kbd-status.json")
)
CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
) / "omarchy-thinkpad-kbd"
CONFIG_PATH = CONFIG_DIR / "config.json"

ACTIVE_STATES = {
    "session_start",
    "thinking",
    "tool_command",
    "tool_edit",
    "tool_read",
    "tool_agent",
    "error",
    "attention",
    "complete",
}

VALID_MODES = {"adaptive", "static", "off"}

# Pattern frames: list of (level: 0|1|2, duration_sec: float)
# One-shot states play once (or for their defined cycles) then return to idle.
# Looping states repeat until another event arrives or inactivity timeout expires.
PATTERNS: Dict[str, Tuple[bool, List[Tuple[int, float]]]] = {
    # (loop, [(level, seconds), ...])
    "session_start": (
        False,
        [(0, 0.12), (1, 0.22), (2, 0.35), (1, 0.25)],
    ),
    "thinking": (
        True,
        [(1, 0.70), (2, 0.70)],
    ),
    "tool_command": (
        True,
        [(2, 0.14), (1, 0.12), (2, 0.14), (0, 0.36)],
    ),
    "tool_edit": (
        True,
        [(2, 0.10), (1, 0.14), (2, 0.09), (1, 0.10), (2, 0.16), (1, 0.22)],
    ),
    "tool_read": (
        True,
        [(0, 0.22), (1, 0.30), (2, 0.24), (1, 0.30)],
    ),
    "tool_agent": (
        True,
        [(2, 0.13), (0, 0.11), (1, 0.13), (2, 0.13), (1, 0.11)],
    ),
    "error": (
        False,
        [
            (2, 0.14),
            (0, 0.14),
            (2, 0.14),
            (0, 0.14),
            (2, 0.14),
            (0, 0.28),
            (2, 0.14),
            (0, 0.14),
            (2, 0.14),
            (0, 0.25),
        ],
    ),
    "attention": (
        False,
        [
            (2, 0.30),
            (0, 0.20),
            (2, 0.30),
            (0, 0.55),
            (2, 0.30),
            (0, 0.20),
            (2, 0.30),
            (0, 0.30),
        ],
    ),
    "complete": (
        False,
        [
            (0, 0.12),
            (1, 0.12),
            (2, 0.28),
            (1, 0.12),
            (0, 0.18),
            (1, 0.12),
            (2, 0.34),
            (1, 0.14),
        ],
    ),
}

DEFAULT_INACTIVITY_TIMEOUT = 120.0


class BacklightController:
    """Reads and writes tpacpi::kbd_backlight safely without sudo."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._last_written: Optional[int] = None
        self.max_level = self._read_max_level()
        self._simulated_level = self.read_level()

    def _read_max_level(self) -> int:
        try:
            val = int(LED_MAX_SYSFS.read_text().strip())
            return max(1, val)
        except Exception:
            return 2

    def read_level(self) -> int:
        if self.dry_run:
            return getattr(self, "_simulated_level", 0)
        try:
            return max(0, min(self.max_level, int(LED_SYSFS.read_text().strip())))
        except Exception:
            return self._last_written if self._last_written is not None else 0

    def set_level(self, level: int, force: bool = False) -> bool:
        clamped = max(0, min(self.max_level, int(level)))
        if not force and self._last_written == clamped:
            return True
        if self.dry_run:
            self._simulated_level = clamped
            self._last_written = clamped
            return True

        # Fast path: direct sysfs write (if user has udev permissions)
        try:
            LED_SYSFS.write_text(f"{clamped}\n")
            self._last_written = clamped
            return True
        except OSError:
            pass

        # Standard path: brightnessctl via systemd-logind D-Bus (no sudo needed)
        try:
            res = subprocess.run(
                ["brightnessctl", "-q", "-d", LED_NAME, "set", str(clamped)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0:
                self._last_written = clamped
                return True
        except Exception:
            pass
        return False


@dataclass
class DaemonConfig:
    enabled: bool = True
    mode: str = "adaptive"  # adaptive | static | off
    resting_level: Optional[int] = None
    inactivity_timeout: float = DEFAULT_INACTIVITY_TIMEOUT

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "DaemonConfig":
        cfg = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if isinstance(data.get("enabled"), bool):
                    cfg.enabled = data["enabled"]
                if data.get("mode") in VALID_MODES:
                    cfg.mode = data["mode"]
                rl = data.get("resting_level")
                if isinstance(rl, int) and 0 <= rl <= 2:
                    cfg.resting_level = rl
                timeout = data.get("inactivity_timeout")
                if isinstance(timeout, (int, float)) and 5 <= timeout <= 3600:
                    cfg.inactivity_timeout = float(timeout)
        except Exception:
            pass
        return cfg

    def save(self, path: Path = CONFIG_PATH) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "enabled": self.enabled,
                "mode": self.mode,
                "resting_level": self.resting_level,
                "inactivity_timeout": self.inactivity_timeout,
            }
            fd, tmp = tempfile.mkstemp(prefix=".cfg-", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2)
                    fh.write("\n")
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            pass


class ThinkPadKbdDaemon:
    def __init__(
        self,
        socket_path: Path = SOCKET_PATH,
        status_path: Path = STATUS_PATH,
        config_path: Path = CONFIG_PATH,
        dry_run: bool = False,
    ) -> None:
        self.socket_path = socket_path
        self.status_path = status_path
        self.config_path = config_path
        self.hw = BacklightController(dry_run=dry_run)
        self.config = DaemonConfig.load(config_path)

        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop_event = threading.Event()

        self._state: str = "idle"
        self._detail: str = ""
        self._state_seq: int = 0
        self._state_started: float = time.monotonic()
        self._state_deadline: Optional[float] = None
        self._is_preview: bool = False
        self._saved_level: Optional[int] = None
        self._current_level: int = self.hw.read_level()

        if self.config.resting_level is None:
            self.config.resting_level = self._current_level

    def _effective_resting_level(self) -> int:
        if self.config.mode == "off":
            return 0
        if self._saved_level is not None:
            return self._saved_level
        if self.config.resting_level is not None:
            return self.config.resting_level
        return self.hw.read_level()

    def _write_status_locked(self) -> None:
        payload = {
            "running": True,
            "device": LED_NAME,
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "state": self._state,
            "active": self._state != "idle",
            "preview": self._is_preview,
            "detail": self._detail,
            "level": self._current_level,
            "max_level": self.hw.max_level,
            "resting_level": self._effective_resting_level(),
            "updated_at": round(time.time(), 3),
        }
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                prefix=".status-", dir=str(self.status_path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                    fh.write("\n")
                os.replace(tmp, self.status_path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            pass

    def get_status(self) -> dict:
        with self._lock:
            if self._state == "idle":
                self._current_level = self.hw.read_level()
            return {
                "ok": True,
                "running": True,
                "device": LED_NAME,
                "enabled": self.config.enabled,
                "mode": self.config.mode,
                "state": self._state,
                "active": self._state != "idle",
                "preview": self._is_preview,
                "detail": self._detail,
                "level": self._current_level,
                "max_level": self.hw.max_level,
                "resting_level": self._effective_resting_level(),
            }

    def handle_command(self, msg: dict) -> dict:
        cmd = str(msg.get("cmd") or "").strip().lower()
        if cmd == "status":
            return self.get_status()

        if cmd == "ping":
            return {"ok": True, "pong": True}

        if cmd == "event":
            state = str(msg.get("event") or "").strip().lower()
            detail = str(msg.get("detail") or msg.get("tool") or "").strip()[:64]
            if state == "idle":
                self._set_idle()
                return self.get_status()
            if state not in ACTIVE_STATES:
                return {"ok": False, "error": f"unknown event: {state}"}
            self._trigger_state(state, detail=detail, is_preview=False)
            return self.get_status()

        if cmd == "preview":
            state = str(msg.get("state") or "").strip().lower()
            aliases = {
                "think": "thinking",
                "run": "tool_command",
                "command": "tool_command",
                "edit": "tool_edit",
                "read": "tool_read",
                "agent": "tool_agent",
                "done": "complete",
                "start": "session_start",
            }
            state = aliases.get(state, state)
            if state not in ACTIVE_STATES:
                return {"ok": False, "error": f"unknown preview state: {state}"}
            duration = msg.get("duration")
            try:
                dur_val = float(duration) if duration is not None else 2.6
            except (TypeError, ValueError):
                dur_val = 2.6
            dur_val = max(0.5, min(15.0, dur_val))
            self._trigger_state(
                state, detail="preview", is_preview=True, preview_duration=dur_val
            )
            return self.get_status()

        if cmd == "set_enabled":
            enabled = bool(msg.get("enabled"))
            with self._lock:
                self.config.enabled = enabled
                if enabled and self.config.mode == "off":
                    self.config.mode = "adaptive"
                self.config.save(self.config_path)
                if not enabled:
                    self._cancel_to_idle_locked()
                else:
                    self._write_status_locked()
            return self.get_status()

        if cmd == "set_mode":
            mode = str(msg.get("mode") or "").strip().lower()
            if mode not in VALID_MODES:
                return {"ok": False, "error": f"invalid mode: {mode}"}
            with self._lock:
                self.config.mode = mode
                self.config.enabled = mode == "adaptive"
                self.config.save(self.config_path)
                if mode == "off":
                    self._saved_level = 0
                    self._cancel_to_idle_locked(force_level=0)
                elif mode == "static":
                    self._cancel_to_idle_locked()
                else:
                    self._write_status_locked()
            return self.get_status()

        if cmd == "set_level":
            raw = msg.get("level")
            try:
                level = int(raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"invalid level: {raw}"}
            level = max(0, min(self.hw.max_level, level))
            with self._lock:
                self.config.resting_level = level
                if level > 0 and self.config.mode == "off":
                    self.config.mode = "static"
                self.config.save(self.config_path)
                self._saved_level = level
                if self._state == "idle":
                    self.hw.set_level(level, force=True)
                    self._current_level = level
                self._write_status_locked()
            return self.get_status()

        return {"ok": False, "error": f"unknown command: {cmd}"}

    def _trigger_state(
        self,
        state: str,
        detail: str = "",
        is_preview: bool = False,
        preview_duration: Optional[float] = None,
    ) -> None:
        with self._lock:
            if not is_preview and (not self.config.enabled or self.config.mode != "adaptive"):
                return
            if self._state == "idle":
                current = self.hw.read_level()
                self._saved_level = current
                self.config.resting_level = current

            self._state = state
            self._detail = detail
            self._is_preview = is_preview
            self._state_seq += 1
            now = time.monotonic()
            self._state_started = now

            loop, _ = PATTERNS[state]
            if is_preview and loop:
                self._state_deadline = now + (preview_duration or 2.6)
            elif loop:
                self._state_deadline = now + self.config.inactivity_timeout
            else:
                self._state_deadline = None

            self._write_status_locked()
            self._wakeup.set()

    def _set_idle(self) -> None:
        with self._lock:
            self._cancel_to_idle_locked()

    def _cancel_to_idle_locked(self, force_level: Optional[int] = None) -> None:
        was_active = self._state != "idle"
        self._state = "idle"
        self._detail = ""
        self._is_preview = False
        self._state_deadline = None
        self._state_seq += 1
        target = force_level if force_level is not None else self._effective_resting_level()
        if was_active or force_level is not None:
            self.hw.set_level(target, force=True)
            self._current_level = target
        self._saved_level = None
        self._write_status_locked()
        self._wakeup.set()

    def _animator_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                state = self._state
                seq = self._state_seq
                deadline = self._state_deadline

            if state == "idle":
                self._wakeup.wait(timeout=1.0)
                self._wakeup.clear()
                continue

            loop, frames = PATTERNS[state]
            completed_naturally = True

            while not self._stop_event.is_set():
                for level, duration in frames:
                    with self._lock:
                        if self._state_seq != seq or self._state != state:
                            completed_naturally = False
                            break
                        if deadline is not None and time.monotonic() >= deadline:
                            completed_naturally = True
                            loop = False
                            break
                        self.hw.set_level(level)
                        self._current_level = level
                        self._write_status_locked()

                    if self._wakeup.wait(timeout=duration):
                        self._wakeup.clear()
                        with self._lock:
                            if self._state_seq != seq or self._state != state:
                                completed_naturally = False
                                break
                    if self._stop_event.is_set():
                        completed_naturally = False
                        break

                if not completed_naturally or not loop:
                    break

            if completed_naturally and not self._stop_event.is_set():
                with self._lock:
                    if self._state_seq == seq and self._state == state:
                        self._cancel_to_idle_locked()

    def _serve_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(1.0)
            chunks: List[bytes] = []
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                chunks.append(data)
                if b"\n" in data or sum(len(c) for c in chunks) > 16384:
                    break
            raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
            if not raw:
                resp = {"ok": False, "error": "empty request"}
            else:
                try:
                    msg = json.loads(raw.splitlines()[0])
                    if not isinstance(msg, dict):
                        resp = {"ok": False, "error": "request must be a JSON object"}
                    else:
                        resp = self.handle_command(msg)
                except json.JSONDecodeError as exc:
                    resp = {"ok": False, "error": f"invalid json: {exc}"}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def run(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.socket_path.exists() or self.socket_path.is_symlink():
                self.socket_path.unlink()
        except OSError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(32)
        server.settimeout(0.5)

        with self._lock:
            if self.config.mode == "off":
                self.hw.set_level(0, force=True)
                self._current_level = 0
            self._write_status_locked()

        animator = threading.Thread(target=self._animator_loop, daemon=True)
        animator.start()

        try:
            while not self._stop_event.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(
                    target=self._serve_client, args=(conn,), daemon=True
                ).start()
        finally:
            self._stop_event.set()
            self._wakeup.set()
            with self._lock:
                if self._state != "idle":
                    restore = self._effective_resting_level()
                    self.hw.set_level(restore, force=True)
                    self._current_level = restore
                    self._state = "idle"
                self._write_status_locked()
            try:
                server.close()
            except Exception:
                pass
            try:
                if self.socket_path.exists():
                    self.socket_path.unlink()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        self._wakeup.set()


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    daemon = ThinkPadKbdDaemon(dry_run=dry_run)

    def _handle_sig(_signum: int, _frame: object) -> None:
        daemon.stop()

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)
    daemon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
