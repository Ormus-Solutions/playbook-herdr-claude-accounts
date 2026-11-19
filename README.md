# A dash of all Claude accounts and their resets

One Herdr pane that lists every Claude Code account you use: its plan, how
full its 5-hour and weekly windows are, when each one resets, and the account
to use next on top.

## What it is

Each Claude Code account is a config dir: the folder you set
`CLAUDE_CONFIG_DIR` to when you start it, or `~/.claude` for the default
account. Claude Code already knows each account's usage: after every update it
hands it to the status line command as JSON. A small status line hook copies
those numbers, and nothing else, into a file in the account's folder. The dash
reads those files and sorts the accounts so the one with the most room comes
first. The pattern is a snapshot file: the program that has the data writes it
down, and the program that shows it only reads files. It works because the
dash never needs a login, a token or the network: Claude Code has done that
part already, with its own login.

## What it saved me

In my words: "A dash with all my Claude accounts and their resets, making
management easy." One look answers two questions: which account to start
next, and when a full one comes back.

## Who it is for

- You run Claude Code with more than one subscription account (personal,
  work, a second seat) and switch when one is full.
- You use Herdr, or any terminal: the dash is a plain terminal program, and
  Herdr only gives it a tab.

Skip it if you have one account (`/usage` inside Claude Code already shows
you everything), or if you log in with an API key: an API key login has no
usage windows, so there is nothing to show.

## Requirements

| Tool | Version | Check |
|---|---|---|
| Python | 3.11 or newer | `python3 --version` |
| git | any recent version | `git --version` |
| Claude Code | 2.1.80 or newer: the status line input got `rate_limits` then (the schema was read from 2.1.328) | `claude --version` |
| A subscription login in each account | Pro or Max | `/usage` inside Claude Code shows the windows |
| [Herdr](https://herdr.dev) | 0.9.5 (tested); optional, the dash runs in any terminal | `herdr --version` |

## Quick start

### Hand it to your agent

```bash
git clone https://github.com/Ormus-Solutions/playbook-herdr-claude-accounts
cd playbook-herdr-claude-accounts
```

Clone this repo, open your coding agent (Claude Code, Codex, Grok) inside the
clone, and paste this:

```text
Read PLAYBOOK.md in this repo and follow it step by step. After each step,
run its "Verify:" command and compare the result with "Expected:". If they
differ, stop and tell me what you saw. Ask me before any step that changes
something outside this repo, and ask me which folders are my Claude accounts
and what label each one should show. Never print a token or an e-mail. When
you finish, run the "Done when" checks and show me their output.
```

### Do it by hand

1. See the demo, with no setup: `bash examples/run.sh`
2. Copy the example config and list your accounts in it, one `[[accounts]]`
   table per config dir, with a label you choose. The copy skips a config
   that is already there, so your accounts are kept:
   `mkdir -p ~/.config/playbook-herdr-claude-accounts && { [ -e ~/.config/playbook-herdr-claude-accounts/config.toml ] || cp examples/config.example.toml ~/.config/playbook-herdr-claude-accounts/config.toml; }`
3. Add the hook to each account:
   `python3 src/install_hook.py install ~/.claude-work`
4. Start Claude Code as each account once and send one message, so the hook
   gets its first numbers: `CLAUDE_CONFIG_DIR=~/.claude-work claude`
5. Look at it once: `python3 src/accounts_dash.py`
6. Give it a Herdr tab: from a shell inside Herdr run `scripts/herdr-tab.sh`,
   or open a new tab, name it `Claude accounts` when Herdr asks, and run
   `python3 src/accounts_dash.py --watch` in this repo (r refreshes, q quits).

## Preview

The output of `bash examples/run.sh` on the five synthetic accounts in
`examples/demo/` (in a terminal, the bars are green, yellow and red):

```text
Claude accounts  Thu 15 Jan 10:00 UTC
Use next: side (fullest window 12%)

  side      Pro      read 4m ago
    5h    ██░░░░░░░░░░░░░░░░░░   12%* resets in 2h 10m (Thu 12:10)
    week  █░░░░░░░░░░░░░░░░░░░    6%  resets in 4d 5h (Mon 15:00)
  main      Max 20x  read now
    5h    ████████░░░░░░░░░░░░   41%  resets in 3h 5m (Thu 13:05)
    week  ███████████░░░░░░░░░   55%* resets in 2d 8h (Sat 18:00)
  night     Max 5x   full until Thu 11:30 (in 1h 30m) · read 12m ago
    5h    ████████████████████  100%* resets in 1h 30m (Thu 11:30)
    week  ██████████████░░░░░░   72%  resets in 5d 0h (Tue 10:00)
  research  Max 5x   full until Sat 13:00 (in 2d 3h) · read 2h ago
    5h    ░░░░░░░░░░░░░░░░░░░░    0%  reset since the reading (was 87%)
    week  ████████████████████  100%* resets in 2d 3h (Sat 13:00)
  spare     ?        no reading yet: start Claude Code with this account once

* the fullest window: it stops the account first
```

How to read it: the accounts with room come first, the emptiest on top. On a
tie, the one that resets first wins, because its unused room is lost at the
reset. Full accounts follow, the one that is free again soonest first. A
window whose reset time has passed counts as empty, even when that account has
not run since (`research` above).

## Files

| Path | What it is |
|---|---|
| `PLAYBOOK.md` | the steps, for an agent or a person |
| `src/accounts_dash.py` | the dash: `--demo`, `--watch` for the pane, `--json` for scripts |
| `src/usage_snapshot.py` | the status line hook: copies the usage numbers into the account's folder |
| `src/install_hook.py` | adds the hook to an account's `settings.json`, and takes it out again |
| `scripts/herdr-tab.sh` | opens the dash in a new Herdr tab |
| `examples/config.example.toml` | the config to copy and change |
| `examples/demo/` | five synthetic accounts and a synthetic status line input |
| `examples/expected-output.txt` | what `examples/run.sh` must print |
| `examples/herdr-popup.toml` | a Herdr key that opens the dash as a popup |
| `tests/` | offline tests that pin the behaviour on the synthetic data |
| `check.sh` | the one gate: tests, shellcheck, placeholders, scrub |
| `scripts/scrub.sh` | the scrub check, copied unchanged from playbook-packaging |
| `CHANGELOG.md` | what changed, newest first |

## Credits

Made by Ormus (Ormus Solutions). Packaged with
[playbook-packaging](https://github.com/Ormus-Solutions/playbook-packaging),
the playbook that sets how these playbook repos are packaged. MIT license.
