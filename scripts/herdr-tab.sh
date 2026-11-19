#!/usr/bin/env bash
# herdr-tab.sh: open the dash in a new Herdr tab named "Claude accounts".
#
# Run it from a shell inside a Herdr pane. Arguments after it go to the dash,
# for example: scripts/herdr-tab.sh --demo
#
# It makes the tab with `herdr tab create`, reads the new pane's id from the
# JSON reply, and starts the dash there with `herdr pane run`. Your focus stays
# where it is (--no-focus). It closes nothing and changes no Herdr setting.
set -euo pipefail

if [ "${HERDR_ENV:-}" != 1 ]; then
  echo "herdr-tab: run this from a pane inside Herdr (HERDR_ENV is not 1)." >&2
  echo "By hand: open a new tab in Herdr, cd to this repo, and run:" >&2
  echo "  python3 src/accounts_dash.py --watch" >&2
  exit 2
fi
if ! command -v herdr >/dev/null 2>&1; then
  echo "herdr-tab: the herdr command is not on PATH" >&2
  exit 2
fi

repo=$(cd "$(dirname "$0")/.." && pwd)
where=()
if [ -n "${HERDR_WORKSPACE_ID:-}" ]; then
  where=(--workspace "$HERDR_WORKSPACE_ID")  # the workspace this pane is in
fi

# ${where[@]+...} keeps an empty list working under set -u in the bash 3.2 of macOS.
reply=$(herdr tab create ${where[@]+"${where[@]}"} --label "Claude accounts" --cwd "$repo" --no-focus)
if ! pane=$(printf '%s' "$reply" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])
except (ValueError, KeyError, TypeError):
    sys.exit(1)
'); then
  echo "herdr-tab: the tab was made, but its pane id was not in the reply." >&2
  echo "Run the dash in that tab by hand: python3 src/accounts_dash.py --watch" >&2
  exit 1
fi

# The absolute path: a shell startup file that changes folder cannot break it.
command="python3 $(printf '%q' "$repo/src/accounts_dash.py") --watch"
for arg in "$@"; do
  command+=" $(printf '%q' "$arg")"
done
herdr pane run "$pane" "$command" >/dev/null
echo "herdr-tab: the dash runs in the tab \"Claude accounts\" (pane $pane)"
