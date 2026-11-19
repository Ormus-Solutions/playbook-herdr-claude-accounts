#!/usr/bin/env python3
"""accounts_dash.py: a dash of all your Claude Code accounts and their resets.

Each Claude Code account is a config dir: the folder in CLAUDE_CONFIG_DIR, or
~/.claude for the default account. The status line hook (usage_snapshot.py)
copies the usage numbers Claude Code already has into a small file in that
folder. This dash reads those files and prints one view: each account with
its plan, its 5-hour and weekly windows, when each resets, and the account
to use next on top.

Per account it reads only:
  - <config_dir>/accounts-dash-usage.json, the numbers the hook wrote;
  - one field of Claude Code's own <config_dir>/.claude.json: the plan name
    (oauthAccount.planDisplayName). For ~/.claude that file is ~/.claude.json.
It never opens a credentials file and never shows an e-mail: each account
shows the label you chose in the config.

Usage:
    python3 src/accounts_dash.py --demo          # synthetic accounts, fixed clock
    python3 src/accounts_dash.py                 # your accounts, printed once
    python3 src/accounts_dash.py --watch         # the live pane: r refreshes, q quits
    python3 src/accounts_dash.py --json          # the same data, for scripts and agents
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG = ROOT / "examples" / "demo" / "config.toml"
DEMO_NOW = 1768471200.0  # Thu 15 Jan 2026 10:00 UTC, the clock of the synthetic data
DEFAULT_CONFIG = Path("~/.config/playbook-herdr-claude-accounts/config.toml")
SNAPSHOT = "accounts-dash-usage.json"  # written by usage_snapshot.py
LABELS = {"five_hour": "5h", "seven_day": "week", "spend_limit": "spend"}
FIRST = ("five_hour", "seven_day")  # shown first, in this order
TOP_KEYS = {"accounts", "refresh_seconds", "full_at"}
ACCOUNT_KEYS = {"label", "config_dir", "plan"}
MAX_LABEL = 24
BAR_WIDTH = 20
ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")


# ---------------------------------------------------------------- settings


@dataclass
class Settings:
    accounts: list[tuple[str, Path, str | None]]  # (label, config dir, plan override)
    refresh_seconds: float = 30.0
    full_at: float = 100.0


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_config(config: dict) -> list[str]:
    """Every problem in the config, so one run shows them all."""
    problems = [f"unknown key '{k}' (known: {', '.join(sorted(TOP_KEYS))})"
                for k in config if k not in TOP_KEYS]
    refresh = config.get("refresh_seconds", 30)
    if not is_number(refresh) or refresh < 5:
        problems.append("'refresh_seconds' must be a number of 5 or more")
    full_at = config.get("full_at", 100)
    if not is_number(full_at) or not 1 <= full_at <= 100:
        problems.append("'full_at' must be a number from 1 to 100")
    accounts = config.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        problems.append("add at least one [[accounts]] table with a label and a config_dir")
        return problems
    seen: set[str] = set()
    for n, acct in enumerate(accounts, 1):
        where = f"account {n}"
        if not isinstance(acct, dict):
            problems.append(f"{where}: must be an [[accounts]] table")
            continue
        problems += [f"{where}: unknown key '{k}' (known: {', '.join(sorted(ACCOUNT_KEYS))})"
                     for k in acct if k not in ACCOUNT_KEYS]
        label = acct.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
            problems.append(f"{where}: 'label' must be a name of 1 to {MAX_LABEL} characters")
        elif "@" in label:
            problems.append(f"{where}: use a short name as 'label', not an e-mail "
                            "(the dash never shows e-mails)")
        elif label in seen:
            problems.append(f"{where}: the label '{label}' is used twice")
        else:
            seen.add(label)
        if not isinstance(acct.get("config_dir"), str) or not acct["config_dir"].strip():
            problems.append(f"{where}: 'config_dir' must be a folder, for example \"~/.claude\"")
        if "plan" in acct and not isinstance(acct["plan"], str):
            problems.append(f"{where}: 'plan' must be text, for example \"Max 5x\"")
    return problems


def load_config(path: Path) -> Settings:
    """Read the TOML config. A relative config_dir is taken from the config's own folder."""
    path = path.expanduser()
    if not path.is_file():
        raise SystemExit(f"no config at {path}: copy examples/config.example.toml there "
                         "and change it, or pass --config")
    try:
        with path.open("rb") as f:
            config = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"config {path}: not valid TOML ({e})") from None
    problems = check_config(config)
    if problems:
        raise SystemExit(f"config {path}:\n  " + "\n  ".join(problems))
    accounts = []
    for acct in config["accounts"]:
        folder = Path(acct["config_dir"]).expanduser()
        if not folder.is_absolute():
            folder = path.parent / folder
        accounts.append((acct["label"].strip(), folder, acct.get("plan")))
    return Settings(accounts, float(config.get("refresh_seconds", 30)),
                    float(config.get("full_at", 100)))


# ---------------------------------------------------------------- the data


@dataclass
class Window:
    key: str  # five_hour, seven_day, ...
    pct: float  # the use when the hook read it
    resets_at: float | None  # Unix seconds

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key)

    def passed(self, now: float) -> bool:
        return self.resets_at is not None and self.resets_at <= now

    def used(self, now: float) -> float:
        """The use now. After its reset time a window is empty again, even when
        the account has not run since, so an old reading does not hide room."""
        return 0.0 if self.passed(now) else self.pct


@dataclass
class Account:
    label: str
    plan: str
    state: str  # "ok", "no reading" or "unreadable"
    windows: list[Window] = field(default_factory=list)
    read_at: float | None = None
    order: int = 0  # its place in the config, for ties


def read_plan(config_dir: Path, home: Path) -> str | None:
    """The plan name Claude Code saved at login, and only that field."""
    files = [config_dir / ".claude.json"]
    if config_dir.resolve() == (home / ".claude").resolve():
        files.append(home / ".claude.json")  # the default account keeps it in the home folder
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        account = data.get("oauthAccount") if isinstance(data, dict) else None
        name = account.get("planDisplayName") if isinstance(account, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()[:20]
    return None


def parse_windows(raw: object) -> list[Window]:
    if not isinstance(raw, dict):
        return []
    out = []
    for key, w in raw.items():
        if not isinstance(w, dict) or not is_number(w.get("used_percentage")):
            continue
        reset = w.get("resets_at")
        out.append(Window(str(key), max(0.0, float(w["used_percentage"])),
                          float(reset) if is_number(reset) else None))
    rank = {k: i for i, k in enumerate(FIRST)}
    return sorted(out, key=lambda w: (rank.get(w.key, len(FIRST)), w.key))


def read_snapshot(config_dir: Path) -> tuple[str, list[Window], float | None]:
    path = config_dir / SNAPSHOT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "no reading", [], None
    except (OSError, ValueError):
        return "unreadable", [], None
    if not isinstance(data, dict):
        return "unreadable", [], None
    windows = parse_windows(data.get("windows"))
    read_at = float(data["written_at"]) if is_number(data.get("written_at")) else None
    return ("ok" if windows else "unreadable"), windows, read_at


def load_accounts(settings: Settings, home: Path) -> list[Account]:
    out = []
    for n, (label, folder, plan) in enumerate(settings.accounts):
        state, windows, read_at = read_snapshot(folder)
        out.append(Account(label, plan or read_plan(folder, home) or "?", state, windows,
                           read_at, n))
    return out


# ---------------------------------------------------------------- which account next


def limiting(acct: Account, now: float) -> Window | None:
    """The fullest window: the one that stops the account first."""
    return max(acct.windows, key=lambda w: w.used(now), default=None)


def has_room(acct: Account, now: float, full_at: float) -> bool:
    top = limiting(acct, now)
    return acct.state == "ok" and top is not None and top.used(now) < full_at


def free_at(acct: Account, now: float, full_at: float) -> float | None:
    """When a full account has room again: when its last full window resets."""
    full = [w for w in acct.windows if w.used(now) >= full_at]
    if not full:
        return now
    if any(w.resets_at is None for w in full):
        return None
    return max(w.resets_at for w in full if w.resets_at is not None)


def ranked(accounts: list[Account], now: float, full_at: float) -> list[Account]:
    """The account to use next first.

    1. Accounts with room, the emptiest first (the lowest fullest window). On a
       tie, the one that resets first: its unused room is lost at the reset.
    2. Full accounts, the one that has room again soonest first.
    3. Accounts with no reading.
    """
    def key(a: Account) -> tuple[int, float, float, int]:
        if a.state != "ok":
            return (2, 0.0, 0.0, a.order)
        if has_room(a, now, full_at):
            top = limiting(a, now)
            first = min((w.resets_at for w in a.windows
                         if w.resets_at is not None and not w.passed(now)), default=math.inf)
            return (0, top.used(now) if top else 0.0, first, a.order)
        when = free_at(a, now, full_at)
        return (1, math.inf if when is None else when, 0.0, a.order)
    return sorted(accounts, key=key)


# ---------------------------------------------------------------- words


GREEN, YELLOW, RED, DIM, BOLD, OFF = ("\033[32m", "\033[33m", "\033[31m", "\033[2m",
                                      "\033[1m", "\033[0m")


class Paint:
    """ANSI colours on a terminal, plain text anywhere else."""

    def __init__(self, on: bool) -> None:
        self.on = on

    def __call__(self, code: str, text: str) -> str:
        return f"{code}{text}{OFF}" if self.on else text


def span(seconds: float) -> str:
    s = int(seconds)
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{max(m, 1)}m"


def clock(ts: float, tz: tzinfo | None, fmt: str = "%a %H:%M") -> str:
    when = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts).astimezone()
    return when.strftime(fmt)


def resets(ts: float | None, now: float, tz: tzinfo | None) -> str:
    if ts is None:
        return "reset time unknown"
    return f"resets in {span(ts - now)} ({clock(ts, tz)})"


def age(seconds: float) -> str:
    s = int(seconds)
    if s < 120:
        return "now"
    if s < 7200:
        return f"{s // 60}m ago"
    if s < 172800:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def bar(pct: float, full_at: float, paint: Paint) -> str:
    filled = max(0, min(BAR_WIDTH, round(pct / 100 * BAR_WIDTH)))
    code = RED if pct >= full_at else YELLOW if pct >= 0.8 * full_at else GREEN
    return paint(code, "█" * filled) + paint(DIM, "░" * (BAR_WIDTH - filled))


def render(accounts: list[Account], now: float, full_at: float, tz: tzinfo | None,
           colours: bool = False) -> list[str]:
    paint = Paint(colours)
    order = ranked(accounts, now, full_at)
    lines = [f"{paint(BOLD, 'Claude accounts')}  {clock(now, tz, '%a %d %b %H:%M %Z')}"]
    best = order[0] if order and has_room(order[0], now, full_at) else None
    full = [a for a in order if a.state == "ok"]
    if best is not None:
        top = limiting(best, now)
        lines.append(f"Use next: {paint(BOLD, best.label)} "
                     f"(fullest window {top.used(now) if top else 0:.0f}%)")
    elif full:
        when = free_at(full[0], now, full_at)
        lines.append(paint(RED, "No account has room.") + f" First free: {full[0].label}, "
                     + (f"in {span(when - now)} ({clock(when, tz)})." if when else "time unknown."))
    else:
        lines.append("No account has a reading yet: start Claude Code with each account once.")
    lines.append("")
    label_w = max(len(a.label) for a in order)
    plan_w = max(len(a.plan) for a in order)
    for a in order:
        head = f"  {paint(BOLD, a.label.ljust(label_w))}  {a.plan.ljust(plan_w)}  "
        if a.state == "no reading":
            lines.append(head + paint(DIM, "no reading yet: start Claude Code with this account once"))
            continue
        if a.state == "unreadable":
            lines.append(head + paint(YELLOW, "the usage file cannot be read; it is written "
                                              "again on the next status line update"))
            continue
        note = f"read {age(now - a.read_at)}" if a.read_at is not None else "read time unknown"
        if not has_room(a, now, full_at):
            when = free_at(a, now, full_at)
            free = f"full until {clock(when, tz)} (in {span(when - now)})" if when else "full"
            note = f"{paint(RED, free)} · {note}"
        lines.append(head + note)
        top = limiting(a, now)
        for w in a.windows:
            used = w.used(now)
            mark = "*" if len(a.windows) > 1 and w is top and used > 0 else " "
            when_text = (f"reset since the reading (was {w.pct:.0f}%)" if w.passed(now)
                         else resets(w.resets_at, now, tz))
            lines.append(f"    {w.label:<5} {bar(used, full_at, paint)} {used:>4.0f}%{mark} "
                         f"{paint(DIM, when_text)}")
    lines += ["", paint(DIM, "* the window that limits the account now")]
    return lines


def as_json(accounts: list[Account], now: float, full_at: float) -> dict:
    order = ranked(accounts, now, full_at)
    best = order[0] if order and has_room(order[0], now, full_at) else None
    out = []
    for a in order:
        top = limiting(a, now)
        room = has_room(a, now, full_at)
        out.append({
            "label": a.label,
            "plan": a.plan,
            "state": a.state,
            "read_at": a.read_at,
            "has_room": room,
            "free_at": None if room or a.state != "ok" else free_at(a, now, full_at),
            "windows": [{"window": w.key, "label": w.label, "read_percentage": w.pct,
                         "used_percentage": w.used(now), "resets_at": w.resets_at,
                         "limits": w is top} for w in a.windows],
        })
    return {"now": now, "full_at": full_at, "next": best.label if best else None,
            "accounts": out}


# ---------------------------------------------------------------- the live pane


def clip(line: str, cols: int) -> str:
    """Cut a line to `cols` visible characters; colour codes take no room."""
    out, seen, i = [], 0, 0
    while i < len(line):
        m = ANSI.match(line, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        if seen >= cols:
            break
        out.append(line[i])
        seen += 1
        i += 1
    return "".join(out) + (OFF if "\033[" in line else "")


def watch(read: Callable[[], list[Account]], draw: Callable[[list[Account]], list[str]],
          every: float) -> int:
    """Read the files every `every` seconds, redraw each second; q quits, r reads now.

    The screen is the terminal's alternate screen (as in less or top), so the
    shell comes back as it was when the dash quits.
    """
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd) if sys.stdin.isatty() else None
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        if saved is not None:
            tty.setcbreak(fd)
        accounts: list[Account] = []
        last = -math.inf
        while True:
            if time.monotonic() - last >= every:
                accounts = read()
                last = time.monotonic()
            size = shutil.get_terminal_size()
            lines = [*draw(accounts), "r refreshes · q quits"][: max(1, size.lines - 1)]
            sys.stdout.write("\033[H" + "\n".join(clip(l, size.columns) + "\033[K" for l in lines)
                             + "\033[J")
            sys.stdout.flush()
            if saved is None:
                time.sleep(1.0)
                continue
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            key = sys.stdin.read(1) if ready else ""
            if key in ("q", "Q"):
                return 0
            if key in ("r", "R"):
                last = -math.inf
    except KeyboardInterrupt:
        return 0
    finally:
        if saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A dash of all your Claude Code accounts and their resets.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"the config file (default: {DEFAULT_CONFIG})")
    parser.add_argument("--demo", action="store_true",
                        help="show the synthetic accounts in examples/demo, at a fixed clock")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true",
                      help="stay open and refresh: the pane view (r refreshes, q quits)")
    mode.add_argument("--json", action="store_true", help="print the data as JSON")
    args = parser.parse_args(argv)

    settings = load_config(DEMO_CONFIG if args.demo else args.config)
    tz = timezone.utc if args.demo else None  # the demo prints the same text everywhere
    now: Callable[[], float] = (lambda: DEMO_NOW) if args.demo else time.time
    home = Path.home()

    def read() -> list[Account]:
        return load_accounts(settings, home)

    if args.json:
        print(json.dumps(as_json(read(), now(), settings.full_at), indent=2))
        return 0
    colours = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if args.watch:
        return watch(read, lambda accts: render(accts, now(), settings.full_at, tz, colours),
                     settings.refresh_seconds)
    print("\n".join(render(read(), now(), settings.full_at, tz, colours)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
