"""Offline tests for the Herdr parts.

herdr-tab.sh runs against a stub `herdr` on PATH that records its arguments
and answers with the JSON shape Herdr documents, so no live Herdr is touched.
The popup snippet is checked with `herdr config check` on a temp config
folder, when Herdr is installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "scripts" / "herdr-tab.sh"

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$1 $2" in
  "tab create") printf '%s' "$STUB_REPLY" ;;
  "pane run") printf '{"result":{}}' ;;
esac
"""
REPLY = '{"result":{"tab":{"tab_id":"w1:t9"},"root_pane":{"pane_id":"w1:p42"}}}'


def bash_quote(path: Path) -> str:
    """The path as the script quotes it (bash printf %q), so a clone in a folder
    with a space still matches."""
    return subprocess.run(["bash", "-c", 'printf %q "$1"', "_", str(path)],
                          capture_output=True, text=True, check=True).stdout


class HerdrTabTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        stub = self.dir / "bin" / "herdr"
        stub.parent.mkdir()
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.log = self.dir / "calls.log"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_tab(self, *args: str, inside: bool = True, reply: str = REPLY):
        env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}
        env.update(PATH=f"{self.dir / 'bin'}{os.pathsep}{env.get('PATH', '')}",
                   STUB_LOG=str(self.log), STUB_REPLY=reply)
        if inside:
            env.update(HERDR_ENV="1", HERDR_WORKSPACE_ID="w1")
        return subprocess.run(["bash", str(TAB), *args], capture_output=True, text=True, env=env)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_opens_a_tab_and_starts_the_dash_in_it(self) -> None:
        done = self.run_tab("--demo")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), [
            f"tab create --workspace w1 --label Claude accounts --cwd {ROOT} --no-focus",
            f"pane run w1:p42 python3 {bash_quote(ROOT / 'src' / 'accounts_dash.py')}"
            " --watch --demo",
        ])
        self.assertIn("w1:p42", done.stdout)

    def test_refuses_outside_herdr(self) -> None:
        done = self.run_tab(inside=False)
        self.assertEqual(done.returncode, 2)
        self.assertIn("inside Herdr", done.stderr)
        self.assertEqual(self.calls(), [])

    def test_an_odd_reply_stops_before_pane_run(self) -> None:
        done = self.run_tab(reply='{"result":{}}')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(self.calls()), 1)  # tab create only


@unittest.skipIf(shutil.which("herdr") is None, "Herdr is not installed")
class PopupSnippetTest(unittest.TestCase):
    def test_herdr_accepts_the_popup_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "herdr" / "config.toml"
            config.parent.mkdir()
            shutil.copyfile(ROOT / "examples" / "herdr-popup.toml", config)
            env = {**os.environ, "XDG_CONFIG_HOME": tmp}
            done = subprocess.run(["herdr", "config", "check"], capture_output=True, text=True,
                                  env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("config: ok", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
