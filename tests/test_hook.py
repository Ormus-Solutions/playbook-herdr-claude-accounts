"""Offline tests for the status line hook and its installer, in temp folders.

Each test makes its own fake account folder; nothing outside it is read or
written. Run them with: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import accounts_dash as dash  # noqa: E402
import install_hook  # noqa: E402
import usage_snapshot  # noqa: E402

HOOK = ROOT / "src" / "usage_snapshot.py"
INPUT = (ROOT / "examples" / "demo" / "statusline-input.json").read_text(encoding="utf-8")


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "HERDR_ENV")}
    env.update(extra)
    return env


def cli(*args: str) -> int:
    """install_hook.main with its messages caught, so the test output stays clean."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return install_hook.main(list(args))


def run_hook(folder: Path, stdin: str = INPUT, command: str | None = None) -> str:
    """Run the hook as Claude Code does: a shell command, the input on stdin."""
    cmd = command or f"{shlex.quote(sys.executable)} {shlex.quote(str(HOOK))}"
    done = subprocess.run(cmd, shell=True, input=stdin, capture_output=True, text=True,
                          env=clean_env(CLAUDE_CONFIG_DIR=str(folder)), check=True)
    return done.stdout


class TempFolder(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.acct = self.dir / "acct"
        self.acct.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def settings(self) -> dict:
        return json.loads((self.acct / "settings.json").read_text(encoding="utf-8"))


class SnapshotTest(TempFolder):
    def test_keeps_only_the_usage_numbers(self) -> None:
        out = run_hook(self.acct)
        self.assertEqual(out, "5h 23% · week 61%\n")
        path = self.acct / usage_snapshot.SNAPSHOT
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"version", "written_at", "windows"})
        self.assertEqual(data["windows"], {
            "five_hour": {"used_percentage": 23.0, "resets_at": 1768478400.0},
            "seven_day": {"used_percentage": 61.0, "resets_at": 1768665600.0}})
        text = path.read_text(encoding="utf-8")
        for private in ("session", "acme-web", "cost", "transcript", "demo-model"):
            self.assertNotIn(private, text)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_no_rate_limits_keeps_the_last_reading(self) -> None:
        run_hook(self.acct)
        before = (self.acct / usage_snapshot.SNAPSHOT).read_text(encoding="utf-8")
        out = run_hook(self.acct, json.dumps({"model": {"id": "demo"}}))
        self.assertEqual(out, "")
        self.assertEqual((self.acct / usage_snapshot.SNAPSHOT).read_text(encoding="utf-8"), before)

    def test_bad_input_breaks_nothing(self) -> None:
        self.assertEqual(run_hook(self.acct, "not json at all"), "")
        self.assertFalse((self.acct / usage_snapshot.SNAPSHOT).exists())

    def test_odd_windows_are_dropped(self) -> None:
        got = usage_snapshot.windows_of({"rate_limits": {
            "five_hour": {"used_percentage": True, "resets_at": 1},
            "seven_day": {"used_percentage": "61", "resets_at": 1},
            "Bad Key!": {"used_percentage": 5, "resets_at": 1},
            "spend_limit": {"used_percentage": 120.5, "resets_at": "soon", "used_usd": 9},
        }})
        self.assertEqual(got, {"spend_limit": {"used_percentage": 120.5, "resets_at": None}})

    def test_the_earlier_status_line_gets_the_same_input(self) -> None:
        earlier = (f"{shlex.quote(sys.executable)} -c "
                   + shlex.quote("import json, sys; print('earlier:', "
                                 "json.load(sys.stdin)['model']['display_name'])"))
        (self.acct / usage_snapshot.SIDECAR).write_text(
            json.dumps({"previous": {"type": "command", "command": earlier}}))
        self.assertEqual(run_hook(self.acct), "earlier: Demo\n")
        self.assertTrue((self.acct / usage_snapshot.SNAPSHOT).exists())

    def test_the_hook_never_runs_itself_again(self) -> None:
        (self.acct / usage_snapshot.SIDECAR).write_text(json.dumps(
            {"previous": {"type": "command", "command": f"python3 {HOOK}"}}))
        self.assertEqual(run_hook(self.acct), "5h 23% · week 61%\n")


class InstallTest(TempFolder):
    def test_install_status_remove_on_a_new_account(self) -> None:
        self.assertEqual(cli("status", str(self.acct)), 1)
        self.assertEqual(cli("install", str(self.acct)), 0)
        self.assertEqual(self.settings()["statusLine"],
                         {"type": "command", "command": install_hook.hook_command()})
        self.assertEqual(json.loads((self.acct / install_hook.SIDECAR).read_text()),
                         {"previous": None, "created": True})
        self.assertEqual(cli("status", str(self.acct)), 0)
        self.assertEqual(cli("remove", str(self.acct)), 0)
        self.assertEqual(list(self.acct.iterdir()), [])  # as it was: install made settings.json

    def test_a_made_settings_file_stays_when_something_else_was_added(self) -> None:
        install_hook.install(self.acct)
        data = self.settings()
        data["model"] = "demo"  # the person changed a setting meanwhile
        (self.acct / "settings.json").write_text(json.dumps(data))
        install_hook.remove(self.acct)
        self.assertEqual(self.settings(), {"model": "demo"})

    def test_install_twice_changes_nothing(self) -> None:
        install_hook.install(self.acct)
        before = (self.acct / "settings.json").read_text()
        self.assertIn("already installed", install_hook.install(self.acct))
        self.assertEqual((self.acct / "settings.json").read_text(), before)

    def test_a_moved_clone_gets_its_new_path(self) -> None:
        (self.acct / "settings.json").write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "python3 /old/src/usage_snapshot.py"}}))
        self.assertIn("updated", install_hook.install(self.acct))
        self.assertEqual(self.settings()["statusLine"]["command"], install_hook.hook_command())

    def test_an_earlier_status_line_is_kept_and_put_back(self) -> None:
        earlier = {"type": "command", "command": "bash ~/statusline.sh", "padding": 1}
        original = {"model": "demo", "statusLine": earlier, "permissions": {"allow": []}}
        (self.acct / "settings.json").write_text(json.dumps(original))
        os.chmod(self.acct / "settings.json", 0o644)
        install_hook.install(self.acct)
        data = self.settings()
        self.assertEqual(data["statusLine"]["padding"], 1)
        self.assertEqual({k: v for k, v in data.items() if k != "statusLine"},
                         {"model": "demo", "permissions": {"allow": []}})
        self.assertEqual(stat.S_IMODE((self.acct / "settings.json").stat().st_mode), 0o644)
        run_hook(self.acct, command=data["statusLine"]["command"])  # as Claude Code would
        install_hook.remove(self.acct)
        self.assertEqual(self.settings(), original)
        self.assertEqual(sorted(p.name for p in self.acct.iterdir()), ["settings.json"])

    def test_install_keeps_the_layout_and_remove_puts_the_bytes_back(self) -> None:
        # For the default account this is the person's main settings.json: a
        # round trip must leave it as it was, not just equal as JSON.
        earlier = {"type": "command", "command": "bash ~/clock.sh", "padding": 0}
        original = json.dumps({"language": "español → ñ", "statusLine": earlier},
                              indent=4, ensure_ascii=False) + "\n"
        path = self.acct / "settings.json"
        path.write_text(original, encoding="utf-8")
        install_hook.install(self.acct)
        text = path.read_text(encoding="utf-8")
        self.assertIn('\n    "language": "español → ñ"', text)  # 4 spaces, no \u escapes
        self.assertEqual(self.settings()["statusLine"],
                         {"type": "command", "command": install_hook.hook_command(),
                          "padding": 0})
        notes = install_hook.remove(self.acct)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(sorted(p.name for p in self.acct.iterdir()), ["settings.json"])
        self.assertIn("byte for byte", notes[0])

    def test_a_setting_changed_since_install_keeps_the_backup(self) -> None:
        path = self.acct / "settings.json"
        path.write_text(json.dumps({"model": "demo"}), encoding="utf-8")
        install_hook.install(self.acct)
        data = self.settings()
        data["theme"] = "dark"  # the person changed a setting meanwhile
        path.write_text(json.dumps(data), encoding="utf-8")
        notes = install_hook.remove(self.acct)
        self.assertEqual(self.settings(), {"model": "demo", "theme": "dark"})
        self.assertTrue((self.acct / ("settings.json" + install_hook.BACKUP_SUFFIX)).is_file())
        self.assertIn("the backup stays", "\n".join(notes))

    def test_remove_says_put_back_only_when_the_file_is_still_there(self) -> None:
        install_hook.install(self.acct)  # a new account: install makes settings.json
        notes = install_hook.remove(self.acct)
        self.assertFalse((self.acct / "settings.json").exists())
        self.assertFalse(any("put back" in n for n in notes), notes)

    def test_a_linked_settings_file_stays_a_link(self) -> None:
        shared = self.dir / "shared"
        shared.mkdir()
        (shared / "settings.json").write_text("{}")
        (self.acct / "settings.json").symlink_to(shared / "settings.json")
        install_hook.install(self.acct)
        self.assertTrue((self.acct / "settings.json").is_symlink())
        self.assertIn("statusLine", json.loads((shared / "settings.json").read_text()))
        self.assertTrue((shared / install_hook.SIDECAR).exists())
        install_hook.remove(self.acct)
        self.assertTrue((self.acct / "settings.json").is_symlink())
        self.assertEqual(json.loads((shared / "settings.json").read_text()), {})

    def test_a_broken_settings_file_is_left_alone(self) -> None:
        (self.acct / "settings.json").write_text("{broken")
        self.assertEqual(cli("install", str(self.acct)), 2)
        self.assertEqual((self.acct / "settings.json").read_text(), "{broken")
        self.assertEqual(sorted(p.name for p in self.acct.iterdir()), ["settings.json"])

    def test_a_missing_folder_is_refused(self) -> None:
        self.assertEqual(cli("install", str(self.dir / "none")), 2)

    def test_end_to_end_the_dash_shows_what_the_hook_wrote(self) -> None:
        install_hook.install(self.acct)
        run_hook(self.acct, command=self.settings()["statusLine"]["command"])
        config = self.dir / "config.toml"
        config.write_text(f'[[accounts]]\nlabel = "work"\nconfig_dir = "{self.acct}"\n'
                          'plan = "Max 5x"\n')
        accounts = dash.load_accounts(dash.load_config(config), self.dir)
        data = dash.as_json(accounts, 1768471200.0, 100)
        self.assertEqual(data["next"], "work")
        self.assertEqual([w["used_percentage"] for w in data["accounts"][0]["windows"]],
                         [23.0, 61.0])


if __name__ == "__main__":
    unittest.main()
