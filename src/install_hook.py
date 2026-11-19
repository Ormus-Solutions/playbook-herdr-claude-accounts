#!/usr/bin/env python3
"""install_hook.py: add the usage hook to one Claude Code account, or take it out.

    python3 src/install_hook.py install ~/.claude-work
    python3 src/install_hook.py status  ~/.claude-work
    python3 src/install_hook.py remove  ~/.claude-work

Claude Code runs one status line command per account, set in the account's
settings.json under "statusLine". `install` puts usage_snapshot.py there. If
the account already had a status line, install keeps it in a side file
(accounts-dash-hook.json) and the hook runs it, so the line you see does not
change. `remove` puts the old status line back and deletes every file this
playbook wrote for that account.

The pattern is a reversible change: each write records what it replaced, so
nobody has to remember what was there before. When no other setting changed
since install, `remove` puts the backup back, byte for byte.

When settings.json is a link (some account tools share one settings file
between accounts), the change goes through the link to the real file, and the
link stays a link.

Exit codes: 0 done (for status: installed), 1 not installed (status only),
2 a problem that changed nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "usage_snapshot.py"
MARK = "usage_snapshot.py"  # how install and remove recognise the hook
SNAPSHOT = "accounts-dash-usage.json"
SIDECAR = "accounts-dash-hook.json"
BACKUP_SUFFIX = ".accounts-dash.bak"


class HookError(Exception):
    """A problem that stopped the change before anything was written."""


def hook_command() -> str:
    return f"python3 {shlex.quote(str(HOOK))}"


def is_ours(status_line: object) -> bool:
    return isinstance(status_line, dict) and MARK in str(status_line.get("command", ""))


def account_folder(raw: str) -> Path:
    folder = Path(raw).expanduser()
    if not folder.is_dir():
        raise HookError(
            f"{folder} is not a folder. Start Claude Code once as that account "
            f"(CLAUDE_CONFIG_DIR={folder} claude) and log in, then run this again.")
    return folder


def read_settings(path: Path) -> dict:
    """settings.json as a dict; {} when there is none yet. Never guesses at a broken file."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HookError(f"cannot read {path} ({e.__class__.__name__}); fix it by hand "
                        "first. Nothing was changed.") from None
    if not isinstance(data, dict):
        raise HookError(f"{path} is not a JSON object; fix it by hand first. Nothing was changed.")
    return data


def indent_of(path: Path) -> int | str:
    """The indent a JSON file uses (the first indented line), so a rewrite keeps its
    look; 2 spaces for a new file or a file on one line."""
    try:
        found = re.search(r"\n([ \t]+)\S", path.read_text(encoding="utf-8"))
    except OSError:
        found = None
    return found.group(1) if found else 2


def same_but_status_line(backup: Path, data: dict) -> bool:
    """True when the backup holds the same settings as data, the status line aside."""
    try:
        old = json.loads(backup.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(old, dict):
        return False
    old.pop("statusLine", None)
    return old == {k: v for k, v in data.items() if k != "statusLine"}


def write_json(path: Path, data: object, indent: int | str = 2) -> None:
    """Write in one step (a temp file, then a rename), keeping the old file's mode.
    Text such as ñ stays as it is (ensure_ascii=False), not as \\u escapes."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".accounts-dash-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def install(folder: Path) -> str:
    target = (folder / "settings.json").resolve()  # through a link, to the real file
    data = read_settings(target)
    current = data.get("statusLine")
    if is_ours(current):
        if current.get("command") == hook_command():
            return f"already installed in {target}"
        data["statusLine"] = {**current, "command": hook_command()}
        write_json(target, data, indent_of(target))
        return f"updated the hook's path in {target}"
    created = not target.exists()
    if not created:
        shutil.copy2(target, target.with_name(target.name + BACKUP_SUFFIX))
    # "previous" is null when there was no status line; "created" says that
    # settings.json itself is new, so remove can delete it again.
    write_json(target.parent / SIDECAR, {"previous": current, "created": created})
    new = {"type": "command", "command": hook_command()}
    if isinstance(current, dict) and "padding" in current:
        new["padding"] = current["padding"]
    data["statusLine"] = new
    write_json(target, data, indent_of(target))
    kept = "; your earlier status line still shows, the hook runs it" if current else ""
    return f"installed in {target}{kept}"


def remove(folder: Path) -> list[str]:
    target = (folder / "settings.json").resolve()
    sidecar = target.parent / SIDECAR
    backup = target.with_name(target.name + BACKUP_SUFFIX)
    notes: list[str] = []
    keep_backup = False
    if target.is_file():
        data = read_settings(target)
        if is_ours(data.get("statusLine")):
            previous, created, readable = None, False, True
            if sidecar.exists():
                try:
                    record = json.loads(sidecar.read_text(encoding="utf-8"))
                    previous, created = record.get("previous"), record.get("created") is True
                except (OSError, ValueError, AttributeError):
                    readable = False
            if not created and backup.is_file() and same_but_status_line(backup, data):
                # Nothing else changed since install: the backup is the file as it
                # was, byte for byte (layout, escapes, mode), so it goes back whole.
                os.replace(backup, target)
                notes.append(f"put {target} back from its backup, byte for byte")
            else:
                if previous is None:
                    data.pop("statusLine")
                else:
                    data["statusLine"] = previous
                if created and not data:
                    target.unlink()  # install made this file, and nothing else is in it
                    notes.append(f"deleted {target}, which install had made")
                else:
                    write_json(target, data, indent_of(target))
                    keep_backup = backup.is_file()
                    if not readable:
                        notes.append(f"took the hook out of {target}, but the side file could "
                                     f"not be read: your old settings are in {backup}")
                    elif keep_backup:
                        notes.append(f"status line put back in {target}. Other settings "
                                     f"changed since install, so the backup stays: compare "
                                     f"{backup} with it, then delete the backup")
                    else:
                        notes.append(f"status line put back as it was in {target}")
    for path in (sidecar, folder / SNAPSHOT) + (() if keep_backup else (backup,)):
        if path.exists():
            path.unlink()
            notes.append(f"deleted {path}")
    return notes or ["nothing to remove"]


def status(folder: Path) -> tuple[bool, str]:
    target = (folder / "settings.json").resolve()
    installed = is_ours(read_settings(target).get("statusLine"))
    reading = "a usage file is there" if (folder / SNAPSHOT).is_file() else "no usage file yet"
    return installed, f"{'installed' if installed else 'not installed'} in {target}; {reading}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add the usage hook to a Claude Code account, "
                                                 "or take it out.")
    parser.add_argument("action", choices=("install", "status", "remove"))
    parser.add_argument("config_dir", help="the account's config dir, for example ~/.claude-work")
    args = parser.parse_args(argv)
    try:
        folder = account_folder(args.config_dir)
        if args.action == "install":
            print(install(folder))
            return 0
        if args.action == "remove":
            print("\n".join(remove(folder)))
            return 0
        installed, text = status(folder)
        print(text)
        return 0 if installed else 1
    except HookError as e:
        print(f"install_hook: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
