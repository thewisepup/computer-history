#!/bin/sh
# Mutation-test computer_history/, build the kill matrix and write mutants/report.md.
# With a module (e.g. computer_history.store) only that module's mutants run.
set -eu
unset GIT_DIR GIT_WORK_TREE
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
python="$(scripts/venv-python)"
module="${1:-}"
# HOME and the path variables point into a throwaway folder.
sandbox="$(mktemp -d "${TMPDIR:-/tmp}/computer-history-mutate.XXXXXX")"
trap 'rm -rf "$sandbox"' EXIT
export HOME="$sandbox" TMPDIR="$sandbox"
unset COMPUTER_HISTORY_DB COMPUTER_HISTORY_SPOOL
rm -rf mutants
if [ -n "$module" ]; then
  "$python" -m mutmut run "$module*"
else
  "$python" -m mutmut run
fi
"$python" scripts/mutation/matrix.py
if [ -n "$module" ]; then
  "$python" scripts/mutation/report.py report --module "$module"
else
  "$python" scripts/mutation/report.py report
fi
