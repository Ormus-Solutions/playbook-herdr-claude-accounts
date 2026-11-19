"""Offline tests for the dash: they pin its behaviour on synthetic data.

Run them with: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import accounts_dash as dash  # noqa: E402  (the path is set just above)

NOW = dash.DEMO_NOW
H = 3600.0
D = 86400.0


def account(label: str, *windows: tuple[str, float, float | None], order: int = 0,
            state: str = "ok") -> dash.Account:
    return dash.Account(label, "Pro", state, [dash.Window(k, p, r) for k, p, r in windows],
                        NOW - 60, order)


def labels(accounts: list[dash.Account], full_at: float = 100) -> list[str]:
    return [a.label for a in dash.ranked(accounts, NOW, full_at)]


def write_config(folder: Path, text: str) -> Path:
    path = folder / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


class DemoTest(unittest.TestCase):
    def test_run_sh_prints_the_expected_output(self) -> None:
        done = subprocess.run(["bash", str(ROOT / "examples" / "run.sh")],
                              capture_output=True, text=True, check=True)
        expected = (ROOT / "examples" / "expected-output.txt").read_text(encoding="utf-8")
        self.assertEqual(done.stdout, expected)

    def test_no_email_reaches_any_output(self) -> None:
        # The demo's .claude.json files hold example.com addresses on purpose.
        demo_files = list((ROOT / "examples" / "demo" / "home").glob("*/.claude.json"))
        self.assertTrue(any("@example.com" in p.read_text() for p in demo_files))
        for flag in ([], ["--json"]):
            out = subprocess.run([sys.executable, str(ROOT / "src" / "accounts_dash.py"),
                                  "--demo", *flag], capture_output=True, text=True,
                                 check=True).stdout
            self.assertNotIn("@", out)
            self.assertNotIn("Demo user", out)

    def test_json_names_the_next_account(self) -> None:
        out = subprocess.run([sys.executable, str(ROOT / "src" / "accounts_dash.py"),
                              "--demo", "--json"], capture_output=True, text=True,
                             check=True).stdout
        data = json.loads(out)
        self.assertEqual(data["next"], "side")
        self.assertEqual([a["label"] for a in data["accounts"]],
                         ["side", "main", "night", "research", "spare"])


class RankTest(unittest.TestCase):
    def test_the_emptiest_account_comes_first(self) -> None:
        a = account("a", ("five_hour", 50, NOW + H), ("seven_day", 10, NOW + D), order=0)
        b = account("b", ("five_hour", 5, NOW + H), ("seven_day", 30, NOW + D), order=1)
        self.assertEqual(labels([a, b]), ["b", "a"])  # b's fullest is 30, a's is 50

    def test_on_a_tie_the_one_that_resets_first_wins(self) -> None:
        late = account("late", ("seven_day", 20, NOW + 5 * D), order=0)
        soon = account("soon", ("seven_day", 20, NOW + 1 * D), order=1)
        self.assertEqual(labels([late, soon]), ["soon", "late"])

    def test_full_accounts_follow_by_when_they_are_free(self) -> None:
        week = account("week", ("seven_day", 100, NOW + 3 * D), order=0)
        hour = account("hour", ("five_hour", 100, NOW + H), order=1)
        room = account("room", ("seven_day", 90, NOW + D), order=2)
        none = account("none", state="no reading", order=3)
        self.assertEqual(labels([none, week, hour, room]), ["room", "hour", "week", "none"])

    def test_a_window_past_its_reset_counts_as_empty(self) -> None:
        old = account("old", ("five_hour", 100, NOW - 60), ("seven_day", 40, NOW + D))
        self.assertTrue(dash.has_room(old, NOW, 100))
        window = dash.limiting(old, NOW)
        assert window is not None
        self.assertEqual(window.key, "seven_day")

    def test_free_at_waits_for_the_last_full_window(self) -> None:
        both = account("both", ("five_hour", 100, NOW + H), ("seven_day", 100, NOW + 2 * D))
        self.assertEqual(dash.free_at(both, NOW, 100), NOW + 2 * D)

    def test_free_at_is_unknown_without_a_reset_time(self) -> None:
        blind = account("blind", ("seven_day", 100, None))
        self.assertIsNone(dash.free_at(blind, NOW, 100))

    def test_full_at_moves_the_line(self) -> None:
        a = account("a", ("seven_day", 96, NOW + D))
        self.assertTrue(dash.has_room(a, NOW, 100))
        self.assertFalse(dash.has_room(a, NOW, 95))


class RenderTest(unittest.TestCase):
    def test_no_room_names_the_first_account_to_free_up(self) -> None:
        a = account("a", ("seven_day", 100, NOW + 2 * D), order=0)
        b = account("b", ("five_hour", 100, NOW + 2 * H), order=1)
        lines = dash.render([a, b], NOW, 100, timezone.utc)
        self.assertEqual(lines[1], "No account has room. First free: b, in 2h 0m (Thu 12:00).")

    def test_no_reading_at_all(self) -> None:
        lines = dash.render([account("x", state="no reading")], NOW, 100, timezone.utc)
        self.assertIn("No account has a reading yet", lines[1])
        self.assertFalse(any(line.startswith("*") for line in lines))  # no star, no legend

    def test_the_star_marks_the_limiting_window(self) -> None:
        a = account("a", ("five_hour", 30, NOW + H), ("seven_day", 70, NOW + D))
        lines = dash.render([a], NOW, 100, timezone.utc)
        week = next(line for line in lines if line.strip().startswith("week"))
        self.assertIn("70%*", week)
        self.assertEqual(lines[-1], "* the fullest window: it stops the account first")

    def test_one_window_gets_no_star_and_no_legend(self) -> None:
        lines = dash.render([account("a", ("five_hour", 30, NOW + H))], NOW, 100, timezone.utc)
        self.assertFalse(any("*" in line for line in lines))

    def test_colours_only_when_asked(self) -> None:
        a = account("a", ("seven_day", 70, NOW + D))
        self.assertFalse(any("\033[" in line for line in dash.render([a], NOW, 100, timezone.utc)))
        self.assertTrue(any("\033[" in line
                            for line in dash.render([a], NOW, 100, timezone.utc, colours=True)))

    def test_words(self) -> None:
        self.assertEqual(dash.span(3 * D + 7 * H + 59), "3d 7h")
        self.assertEqual(dash.span(4 * H + 29 * 60), "4h 29m")
        self.assertEqual(dash.span(20), "1m")
        self.assertEqual(dash.age(30), "now")
        self.assertEqual(dash.age(9 * 60), "9m ago")
        self.assertEqual(dash.age(5 * H), "5h ago")
        self.assertEqual(dash.age(3 * D), "3d ago")
        self.assertEqual(dash.resets(None, NOW, timezone.utc), "reset time unknown")

    def test_clip_counts_only_visible_characters(self) -> None:
        line = "\033[31mabcdef\033[0m"
        self.assertEqual(dash.ANSI.sub("", dash.clip(line, 3)), "abc")
        self.assertEqual(dash.clip("abcdef", 4), "abcd")


class FilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plan_comes_from_claude_json(self) -> None:
        (self.dir / ".claude.json").write_text(
            json.dumps({"oauthAccount": {"planDisplayName": "Max 5x",
                                         "emailAddress": "x@example.com"}}))
        self.assertEqual(dash.read_plan(self.dir, Path("/nonexistent-home")), "Max 5x")

    def test_the_default_account_keeps_its_plan_in_the_home_folder(self) -> None:
        home = self.dir
        (home / ".claude").mkdir()
        (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"planDisplayName": "Pro"}}))
        self.assertEqual(dash.read_plan(home / ".claude", home), "Pro")
        other = home / ".claude-work"
        other.mkdir()
        self.assertIsNone(dash.read_plan(other, home))  # only the default account looks there

    def test_a_broken_or_odd_claude_json_gives_no_plan(self) -> None:
        (self.dir / ".claude.json").write_text("{not json")
        self.assertIsNone(dash.read_plan(self.dir, self.dir))
        (self.dir / ".claude.json").write_text(json.dumps({"oauthAccount": ["odd"]}))
        self.assertIsNone(dash.read_plan(self.dir, self.dir))

    def test_snapshot_states(self) -> None:
        self.assertEqual(dash.read_snapshot(self.dir)[0], "no reading")
        (self.dir / dash.SNAPSHOT).write_text("{half a fi")
        self.assertEqual(dash.read_snapshot(self.dir)[0], "unreadable")
        (self.dir / dash.SNAPSHOT).write_text(json.dumps({"windows": {"seven_day": {
            "used_percentage": True, "resets_at": 1}}}))
        self.assertEqual(dash.read_snapshot(self.dir)[0], "unreadable")  # a bool is no number
        (self.dir / dash.SNAPSHOT).write_text(json.dumps({"written_at": 5, "windows": {
            "seven_day": {"used_percentage": 40, "resets_at": 9},
            "five_hour": {"used_percentage": 10, "resets_at": 7}}}))
        state, windows, read_at = dash.read_snapshot(self.dir)
        self.assertEqual((state, [w.key for w in windows], read_at),
                         ("ok", ["five_hour", "seven_day"], 5.0))

    def test_a_missing_folder_is_not_an_unused_account(self) -> None:
        # A typo in config_dir must not say "start Claude Code once": the person
        # did that already, in the right folder.
        config = write_config(self.dir, '[[accounts]]\nlabel = "work"\nconfig_dir = "typo"\n')
        accounts = dash.load_accounts(dash.load_config(config), self.dir)
        self.assertEqual(dash.as_json(accounts, NOW, 100)["accounts"][0]["state"], "no folder")
        text = "\n".join(dash.render(accounts, NOW, 100, timezone.utc))
        self.assertIn(f"no folder: {self.dir / 'typo'} does not exist; check config_dir", text)
        self.assertNotIn("start Claude Code with this account once", text)


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def problems(self, text: str) -> str:
        with self.assertRaises(SystemExit) as caught:
            dash.load_config(write_config(self.dir, text))
        return str(caught.exception)

    def test_the_example_config_is_valid(self) -> None:
        settings = dash.load_config(ROOT / "examples" / "config.example.toml")
        self.assertEqual([a[0] for a in settings.accounts], ["main", "work", "side"])
        self.assertEqual(settings.accounts[0][1], Path("~/.claude").expanduser())
        self.assertEqual(settings.accounts[2][2], "Pro")

    def test_a_relative_folder_is_read_from_the_config_folder(self) -> None:
        settings = dash.load_config(write_config(
            self.dir, '[[accounts]]\nlabel = "a"\nconfig_dir = "acct"\n'))
        self.assertEqual(settings.accounts[0][1], self.dir / "acct")

    def test_missing_config_says_what_to_do(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            dash.load_config(self.dir / "none.toml")
        self.assertIn("examples/config.example.toml", str(caught.exception))

    def test_an_email_is_not_a_label(self) -> None:
        text = self.problems('[[accounts]]\nlabel = "me@example.com"\nconfig_dir = "a"\n')
        self.assertIn("not an e-mail", text)

    def test_every_problem_is_listed(self) -> None:
        text = self.problems(
            'refresh_seconds = 1\nfull_at = true\ncolour = "red"\n'
            '[[accounts]]\nlabel = "a"\nconfig_dir = "x"\n'
            '[[accounts]]\nlabel = "a"\nconfigdir = "y"\nplan = 5\n')
        for words in ("'refresh_seconds' must be", "'full_at' must be", "unknown key 'colour'",
                      "used twice", "unknown key 'configdir'", "'config_dir' must be",
                      "'plan' must be text"):
            self.assertIn(words, text)

    def test_no_accounts(self) -> None:
        self.assertIn("at least one [[accounts]]", self.problems("full_at = 90\n"))

    def test_bad_toml(self) -> None:
        self.assertIn("not valid TOML", self.problems("accounts = [\n"))


@unittest.skipUnless(hasattr(os, "openpty"), "needs a Unix terminal")
class WatchTest(unittest.TestCase):
    def test_the_pane_draws_and_q_quits(self) -> None:
        """--watch in a pseudo-terminal (a fake terminal the test holds both ends
        of): it draws the dash, q ends it, and the screen is handed back."""
        import pty

        pid, fd = pty.fork()
        if pid == 0:  # the child: become the dash
            os.execv(sys.executable, [sys.executable, str(ROOT / "src" / "accounts_dash.py"),
                                      "--demo", "--watch"])
        seen = b""
        try:
            while b"q quits" not in seen:
                ready, _, _ = select.select([fd], [], [], 10)
                self.assertTrue(ready, "the dash drew nothing in 10 s")
                seen += os.read(fd, 65536)
            os.write(fd, b"q")
            # A dash that ignores q keeps redrawing each second, so the wait
            # needs a deadline of its own, not only a pause in the output.
            quit_by = time.monotonic() + 10
            while True:
                ready, _, _ = select.select([fd], [], [], 1)
                self.assertLess(time.monotonic(), quit_by, "the dash did not quit on q")
                if not ready:
                    continue
                try:
                    chunk = os.read(fd, 65536)
                except OSError:  # the child closed the terminal
                    break
                if not chunk:
                    break
                seen += chunk
        finally:
            deadline = time.monotonic() + 5
            done, status = os.waitpid(pid, os.WNOHANG)
            while done == 0 and time.monotonic() < deadline:
                time.sleep(0.05)
                done, status = os.waitpid(pid, os.WNOHANG)
            if done == 0:  # still running after a failed check: end it, never hang
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
            os.close(fd)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        text = seen.decode("utf-8", "replace")
        self.assertIn("Use next:", text)
        self.assertIn("\033[?1049h", text)  # it took the alternate screen
        self.assertIn("\033[?1049l", text)  # and gave it back


if __name__ == "__main__":
    unittest.main()
