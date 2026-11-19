#!/usr/bin/env bash
# check.sh: the one gate for this playbook. Run it before every commit and
# before you publish. It stops at the first failure and exits non-zero.
#   1. the tests in tests/ (offline, on the synthetic data)
#   2. shellcheck on every shell script, when shellcheck is installed
#   3. placeholders from the template that are not filled yet
#   4. the scrub: secrets, e-mails, phones, IPs, host names, home paths and
#      your deny-list (see scripts/scrub.sh), plus gitleaks when installed
#   5. with --publish only: every commit's author and committer e-mail is a
#      noreply address. The scrub only warns about it, because a person who
#      works in their own clone has nothing to fix; before a push to a public
#      repo it is a stop, since a pushed e-mail cannot be taken back.
#
# Usage: ./check.sh            the gate for every commit
#        ./check.sh --publish  the gate before the first push to a public repo
set -euo pipefail
cd "$(dirname "$0")"

publish=0
case "${1:-}" in
  "") ;;
  --publish) publish=1 ;;
  *) echo "usage: ./check.sh [--publish]" >&2; exit 2 ;;
esac

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "check: needs Python 3.11 or newer (python3 --version)" >&2
  exit 1
fi

echo "== tests"
python3 -m unittest discover -s tests

echo "== shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck check.sh scripts/*.sh examples/run.sh
  echo "ok"
else
  echo "shellcheck is not installed; skipped"
fi

echo "== placeholders"
# The markers are split in two so this file does not match itself.
if grep -rnF --exclude-dir=.git -e '<''FILL:' -e '{{''slug}}' -e '{{''title}}' \
     -e '{{''year}}' -e '{{''date}}' . ; then
  echo "check: fill the placeholders above, then run again" >&2
  exit 1
fi
echo "none left"

echo "== scrub"
bash scripts/scrub.sh .

if [ "$publish" = 1 ]; then
  echo "== commit e-mails (--publish)"
  # Only noreply addresses pass, because they reach no person. The
  # addresses themselves are never printed, only how many there are.
  personal=$(git log --all --format='%ae%n%ce' |
    grep -civE '(^(no-?reply|git)@|noreply\.github\.com$)' || true)
  if [ "$personal" != 0 ]; then
    echo "check: $personal author or committer e-mails in the history are not noreply" >&2
    echo "addresses. Set a noreply one with" >&2
    echo "git config user.email (GitHub: Settings, Emails), then rewrite the commits:" >&2
    echo "git rebase --root --exec 'git commit --amend --no-edit --reset-author'" >&2
    exit 1
  fi
  echo "all noreply"
fi

echo "check: ok"
