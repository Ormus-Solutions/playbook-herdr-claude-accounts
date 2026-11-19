#!/usr/bin/env python3
"""usage_snapshot.py: the status line hook that records one account's usage.

Claude Code runs a status line command after each update and pipes it one
JSON object on stdin. For a Claude subscription that object has a
`rate_limits` part: the 5-hour window and the weekly window, each with
`used_percentage` (0 to 100) and `resets_at` (Unix seconds). This hook copies
those numbers, and nothing else, into a small file in the account's config
dir: `accounts-dash-usage.json`. The dash (accounts_dash.py) reads that file.

The pattern is a tee: the hook reads its input once, keeps a copy, and hands
the same input to the status line you had before (install_hook.py keeps it in
a side file), so the line you see at the bottom of Claude Code does not change.
With no earlier status line, the hook prints a short one itself.

Why a hook and not an API call: Claude Code has already fetched these numbers
with its own login. The hook opens no token file and makes no network call.

Claude Code runs it; you do not. To try it by hand on synthetic data:
    d=$(mktemp -d)
    CLAUDE_CONFIG_DIR=$d python3 src/usage_snapshot.py < examples/demo/statusline-input.json

It keeps to the standard library and to syntax Python 3.8 can read, because
it runs with whatever `python3` the status line shell finds first.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SNAPSHOT = "accounts-dash-usage.json"  # in the account's config dir
SIDECAR = "accounts-dash-hook.json"  # next to settings.json: the earlier status line
LABELS = {"five_hour": "5h", "seven_day": "week", "spend_limit": "spend"}
WINDOW_KEY = re.compile(r"[a-z0-9_]{1,32}")
PREVIOUS_TIMEOUT = 5.0  # seconds; a status line must never hang Claude Code


def config_dir() -> Path:
    """The account this Claude Code runs as: CLAUDE_CONFIG_DIR, or ~/.claude."""
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".claude"


def number(value: object) -> float | None:
    """A finite int or float; None for anything else (a bool is not a number here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def windows_of(status: object) -> dict[str, dict[str, float | None]]:
    """The usage windows in a status line input, as {key: {used_percentage, resets_at}}.

    Only these two numbers per window are kept. The rest of the input (session
    id, folder, model, cost) never reaches the file.
    """
    limits = status.get("rate_limits") if isinstance(status, dict) else None
    out: dict[str, dict[str, float | None]] = {}
    if not isinstance(limits, dict):
        return out
    for key, window in limits.items():
        if not isinstance(key, str) or not WINDOW_KEY.fullmatch(key) or not isinstance(window, dict):
            continue
        pct = number(window.get("used_percentage"))
        if pct is None:
            continue
        out[key] = {"used_percentage": max(0.0, pct), "resets_at": number(window.get("resets_at"))}
    return out


def write_snapshot(folder: Path, windows: dict[str, dict[str, float | None]], now: float) -> Path:
    """Write the file in one step: a temp file, then a rename over the old one.

    A reader never sees half a file, because a rename on one disk is atomic.
    mkstemp makes the file readable by you only (mode 600).
    """
    data = {"version": 1, "written_at": int(now), "windows": windows}
    fd, tmp = tempfile.mkstemp(prefix=".accounts-dash-", suffix=".tmp", dir=str(folder))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
            f.write("\n")
        os.replace(tmp, folder / SNAPSHOT)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return folder / SNAPSHOT


def previous_command(folder: Path) -> str | None:
    """The status line command that was there before install_hook.py, if any.

    The side file sits next to the real settings.json. When settings.json is a
    link shared by several accounts, every account finds the same side file.
    """
    sidecar = (folder / "settings.json").resolve().parent / SIDECAR
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    previous = data.get("previous") if isinstance(data, dict) else None
    command = previous.get("command") if isinstance(previous, dict) else None
    if not isinstance(command, str) or not command.strip() or "usage_snapshot.py" in command:
        return None  # nothing there, or this hook itself (that would loop)
    return command


def own_line(windows: dict[str, dict[str, float | None]]) -> str:
    parts = []
    for key, window in windows.items():
        pct = window["used_percentage"] or 0.0
        parts.append(f"{LABELS.get(key, key)} {pct:.0f}%")
    return " · ".join(parts)


def main() -> int:
    raw = sys.stdin.read()
    try:
        status = json.loads(raw)
    except ValueError:
        status = None
    folder = config_dir()
    windows = windows_of(status)
    # No rate_limits (an API key login, or before the first answer): keep the
    # last reading instead of writing an empty one.
    if windows and folder.is_dir():
        try:
            write_snapshot(folder, windows, time.time())
        except OSError:
            pass  # a full disk must not break the status line
    command = previous_command(folder)
    if command:
        try:
            done = subprocess.run(command, shell=True, input=raw, capture_output=True,
                                  text=True, timeout=PREVIOUS_TIMEOUT)
            sys.stdout.write(done.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
        return 0
    if windows:
        print(own_line(windows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
