# Omarchy ThinkPad Keyboard Backlight

An [Omarchy](https://omarchy.org/) shell bar plugin + background daemon that drives ThinkPad keyboard backlight (`tpacpi::kbd_backlight`, levels `0`/`1`/`2`) animations from Antigravity (AGY) lifecycle hooks — inspired by [`omarchy_razer`](https://github.com/M30W-M1X/omarchy_razer).

## Features

- **Native Omarchy Top-Bar Plugin (`thinkpad.kbd`)**:
  - Geometric keyboard backlight icon with live glow rays and a pulsing activity dot when AGY is working.
  - Toggle switch (or right-click bar icon) to pause/resume adaptive animations.
  - Direct resting brightness controls (`Off`, `Dim`, `Bright`) and modes (`Adaptive`, `Static`, `Off`).
  - Built-in one-click previews for every activity pattern.
- **Zero-Sudo Hardware Control**: Uses `brightnessctl` via `systemd-logind` D-Bus (with direct sysfs write fast path), always restoring your previous resting backlight level when idle.
- **AGY Lifecycle Hook Map**:
  - `SessionStart` → smooth `0 → 1 → 2 → 1` ignition ramp
  - `PreInvocation` (`thinking`) → calm `1 ↔ 2` breathing pulse
  - `PostToolUse` (`run_command`) → rhythmic double-beat engine pulse
  - `PostToolUse` (`edit_file`, `write_file`) → crisp typing sparks
  - `PostToolUse` (`read_file`, `search_web`) → gentle `0 → 1 → 2 → 1` scan sweep
  - `PostToolUse` (`invoke_subagent`, `swarm`) → energetic shimmer
  - `PostToolUse` / `Stop` (error) → urgent triple-strobe alert
  - `Stop` (`USER_CANCELED`, limit) → double attention beacon
  - `Stop` (`NO_TOOL_CALL`, done) → confirmation double-bloom → restores resting level

## Install / Uninstall

```bash
./install.sh
./uninstall.sh
```

## CLI Usage

```bash
omarchy-thinkpad-kbd status
omarchy-thinkpad-kbd toggle
omarchy-thinkpad-kbd mode adaptive|static|off
omarchy-thinkpad-kbd level 0|1|2
omarchy-thinkpad-kbd preview think|run|edit|read|agent|error|attention|done
```
