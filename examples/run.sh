#!/usr/bin/env bash
# run.sh: see the dash work on the synthetic accounts in examples/demo, with
# no setup. The clock is fixed, so the output is the same on every machine and
# must match examples/expected-output.txt (a test checks it).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 src/accounts_dash.py --demo
