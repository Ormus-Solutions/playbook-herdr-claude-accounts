# A dash of all Claude accounts and their resets: the playbook

This file is written for a coding agent (Claude Code, Codex, Grok) and is
readable by a person. Do the steps in order. Each step is one action, a
"Verify:" command and the result to expect. Stop at the first result that
does not match and report what you saw.

Two rules hold for every step: never print a token or an e-mail address, and
ask the person before a step that changes something outside this repo (steps
3, 5, 6 and 8 do, and so do the popup key under "Adapt it" and every step of
"Undo").

## Goal

A Herdr tab named "Claude accounts" shows every Claude Code account of this
person: its label, its plan, how full its 5-hour and weekly windows are, when
each resets, and the account to use next on top. It refreshes by itself.

How it works, in one line per part:

- Claude Code hands its status line command a JSON object after each update.
  For a subscription login it holds `rate_limits.five_hour` and
  `rate_limits.seven_day`, each with `used_percentage` and `resets_at`.
- `src/usage_snapshot.py` is that status line command. It copies those
  numbers into `accounts-dash-usage.json` in the account's config dir, then
  runs the status line the account had before, if any.
- `src/accounts_dash.py` reads that file in every account folder and draws
  the dash.

## Before you start

| Need | Check | Expected | If it fails |
|---|---|---|---|
| Python 3.11 or newer | `python3 -c 'import sys; print(sys.version_info >= (3, 11))'` | `True` | install a newer Python from python.org or your package manager |
| git | `git --version` | a version line | install git |
| Claude Code 2.1.80 or newer | `claude --version` | `2.1.80` or a later version: the status line input got `rate_limits` in 2.1.80 (Claude Code's changelog); the schema this relies on was read from 2.1.328 | install Claude Code, or update it with `claude update` |
| One config dir per account, each logged in with a Pro or Max subscription | `for d in ~/.claude ~/.claude-*; do [ -d "$d" ] && echo "$d"; done` | one folder per account the person names | make one: `CLAUDE_CONFIG_DIR=~/.claude-work claude`, then `/login` inside it (see the note below) |
| Herdr, for the tab (step 8 only) | `herdr --version` | `herdr 0.9.5` or newer | install Herdr, or skip step 8 and run the dash in any terminal |
| A shell inside Herdr (step 8 only) | `test "${HERDR_ENV:-}" = 1 && echo inside` | `inside` | open a pane in Herdr and run step 8 from there |

A note on accounts. A Claude Code login is a chain of refresh tokens: each
refresh retires the token before it. So log in once in each folder, and never
copy a credentials file from one folder to another: two folders that hold
copies of one login sign each other out. A shell alias makes each account one
word, for example `alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'`.

## Steps

### 1. Run the demo on the synthetic data

This shows what the dash does before anything on the machine changes. The
clock is fixed, so the output is the same everywhere.

```bash
bash examples/run.sh
```

Verify: `bash examples/run.sh | diff - examples/expected-output.txt && echo same`
Expected: `same`

### 2. Run the tests

They run offline, in temp folders, and pin the dash, the hook and the
installer on synthetic data.

```bash
python3 -m unittest discover -s tests
```

Verify: `python3 -m unittest discover -s tests 2>&1 | tail -1`
Expected: `OK`, or `OK (skipped=1)` when Herdr is not installed

### 3. Write the config

Ask the person which folders are their accounts and what label each one
should show. A label is a short word they choose (`main`, `work`); never use
an e-mail, and the dash refuses a label with an `@` in it.

```bash
mkdir -p ~/.config/playbook-herdr-claude-accounts
[ -e ~/.config/playbook-herdr-claude-accounts/config.toml ] || cp examples/config.example.toml ~/.config/playbook-herdr-claude-accounts/config.toml
```

The copy runs only when there is no config yet, so running this step again
keeps the accounts the person already wrote. Then edit that file: one `[[accounts]]` table per account, with `label` and
`config_dir`. Delete the example tables the person does not have.

Verify: `python3 src/accounts_dash.py --json | python3 -c 'import json, sys; print(*[(a["label"], a["state"]) for a in json.load(sys.stdin)["accounts"]])'`
Expected: one `(label, state)` pair per account the person named; the state is `no reading` until step 6, or `ok`.
A state `no folder` means that `config_dir` does not exist: fix the path in the config before step 5, because the hook goes into the folder you name there.

### 4. See what the hook keeps, on synthetic input

The hook reads a status line input and keeps only the usage numbers. This runs
it on `examples/demo/statusline-input.json` in a temp folder, so no account
is touched.

```bash
d=$(mktemp -d) && CLAUDE_CONFIG_DIR=$d python3 src/usage_snapshot.py < examples/demo/statusline-input.json && cat "$d/accounts-dash-usage.json" && rm -rf "$d"
```

Verify: the same command
Expected: the line `5h 23% · week 61%`, then a JSON object with `version`, `written_at` and `windows` only: no session id, folder, model or cost

### 5. Add the hook to each account

This changes each account's `settings.json`: ask the person first. Run it once
per account folder from step 3.

```bash
python3 src/install_hook.py install ~/.claude-work
```

If the account already had a status line, it keeps showing: the installer
moves it to a side file (`accounts-dash-hook.json`) and the hook runs it with
the same input. Its other settings, such as `padding` and `refreshInterval`,
stay on the new status line. If `settings.json` is a link shared by several accounts, the
change goes to the real file; the next folders say `already installed`.

Verify: `python3 src/install_hook.py status ~/.claude-work; echo "exit $?"`
Expected: `installed in .../settings.json; no usage file yet`, then `exit 0`

### 6. Give each account one answer

The status line gets `rate_limits` after the first answer of a session. The
person starts Claude Code as each account and sends one short message, for
example `CLAUDE_CONFIG_DIR=~/.claude-work claude`, then `hi`. This uses their
account, so they do it, or say yes to it.

Verify: `python3 src/install_hook.py status ~/.claude-work`
Expected: `installed in .../settings.json; a usage file is there`

If there is still no usage file, check each of these:

- The login is a subscription: `/usage` inside Claude Code shows windows. An
  API key login has no windows.
- Claude Code is 2.1.80 or newer (`claude --version`); if not, run
  `claude update`.
- The folder you started Claude Code in has no `.claude/settings.json` and no
  `.claude/settings.local.json` with its own `statusLine`. A project setting
  wins over the account's, and the hook then does not run in that project.
  Start it once in a folder without them, for example a new empty folder.
- The trust prompt for that folder was accepted. Claude Code runs no status
  line command in a folder it does not trust yet.

### 7. Look at the dash once

```bash
python3 src/accounts_dash.py
```

Verify: `python3 src/accounts_dash.py --json | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d["next"], *[a["state"] for a in d["accounts"]])'`
Expected: the label of the account to use next, then `ok` for every account from step 6

### 8. Open it as a Herdr tab

From a shell inside a Herdr pane (`HERDR_ENV` is `1`), in this repo:

```bash
scripts/herdr-tab.sh
```

It makes a tab named "Claude accounts" in the current workspace, without
moving the person's focus, and starts `python3 src/accounts_dash.py --watch`
in it. By hand it is the same: open a new tab (the prefix, `ctrl+b` unless it
was changed, then `c`), name it `Claude accounts` when Herdr asks, `cd` to
this repo, and run that command. In the tab, `r` refreshes and `q` quits.

Verify: `herdr tab list --workspace "$HERDR_WORKSPACE_ID" | python3 -c 'import json, sys; print(sum(t["label"] == "Claude accounts" for t in json.load(sys.stdin)["result"]["tabs"]))'`
Expected: `1`, and the tab shows the dash. The command counts the tabs in
Herdr's JSON reply, not lines of text. A `2` means the step ran twice: close
one of the two tabs.

## Adapt it

| Setting | Where | Example |
|---|---|---|
| The accounts | `~/.config/playbook-herdr-claude-accounts/config.toml`, one `[[accounts]]` table each | `label = "work"` and `config_dir = "~/.claude-work"` |
| The plan name shown | `plan` in an `[[accounts]]` table; without it, the plan Claude Code saved at login | `plan = "Max 5x"` |
| When a window counts as full | `full_at`, top of the config | `full_at = 95` moves you on before the wall |
| How often the pane reads the files | `refresh_seconds`, top of the config (5 or more) | `refresh_seconds = 60` |
| Another config file | the `--config` flag | `python3 src/accounts_dash.py --watch --config ~/dash.toml` |
| A key that opens it as a popup | the block in `examples/herdr-popup.toml`, added to `~/.config/herdr/config.toml`; replace `/path/to/playbook-herdr-claude-accounts` in its `command` with the absolute path of your clone (`pwd` in the clone prints it), then run `herdr config check` and `herdr server reload-config`. The check passes with the placeholder still in, so replace it first | `key = "prefix+alt+a"` |
| The tab's name | `--label` in `scripts/herdr-tab.sh` | `--label "Usage"` |
| No colours | the `NO_COLOR` environment variable | `NO_COLOR=1 python3 src/accounts_dash.py` |

## Done when

- `./check.sh` prints `check: ok`.
- `python3 src/install_hook.py status <folder>` exits 0 for every account.
- `python3 src/accounts_dash.py` shows every account with a reading, and its
  "Use next" line names one of them.
- The Herdr tab "Claude accounts" shows the dash, and the "read ... ago" age
  of an account drops back to `now` after the person uses that account.

## Undo

1. In the tab, press `q`, then close the tab (the prefix, then `shift+x`).
2. For each account folder: `python3 src/install_hook.py remove ~/.claude-work`.
   When no other setting changed since install, it puts `settings.json` back
   from `settings.json.accounts-dash.bak`, byte for byte. When one did, it puts
   the old `statusLine` back (or removes the key when there was none), keeps
   the other change, and keeps the backup so the person can compare the two; it
   says so. It deletes `accounts-dash-usage.json` and `accounts-dash-hook.json`.
   A `settings.json` that install made, and that still holds nothing else, is
   deleted too. Check: `python3 src/install_hook.py status ~/.claude-work`
   exits 1 and says `not installed`.
3. Delete the config: `rm -r ~/.config/playbook-herdr-claude-accounts`.
4. If you added the popup key, take its block out of `~/.config/herdr/config.toml`
   and run `herdr server reload-config`.
5. Delete the clone. Run step 2 before this: the hook runs from the clone, so
   a hook left behind would print nothing in the status line.

## Safety

- Reads: the config file; in each account folder, `accounts-dash-usage.json`
  and one field of Claude Code's `.claude.json`, the plan name
  (`oauthAccount.planDisplayName`; for `~/.claude` the file is `~/.claude.json`).
  The hook reads its stdin, which Claude Code sends it, and the side file
  `accounts-dash-hook.json` next to the real `settings.json`, which holds the
  earlier status line command that it runs.
- Writes: the hook writes `accounts-dash-usage.json` in the account folder,
  readable by you only (mode 600): two numbers per window and the time.
  `install_hook.py` writes `settings.json`: the `statusLine` key changes; the
  other keys, their order, the indent of an indented file and text such as
  `ñ` stay. Python's `json` module writes the file again, so other spacing can
  change (`"a":1` becomes `"a": 1`, a file on one line gets a 2-space indent)
  until `remove` puts the original bytes back. It
  also writes `accounts-dash-hook.json` and a backup
  `settings.json.accounts-dash.bak` next to it. The dash writes nothing.
  `scripts/herdr-tab.sh` makes one tab.
- Never: it never opens a credentials file or a keychain, never makes a
  network call, never shows an e-mail (each account shows the label you chose),
  never changes which account is logged in, and never closes a Herdr tab or
  pane.
- Runs: the hook runs the status line command the account had before, with the
  same input, through the shell, as Claude Code did.
