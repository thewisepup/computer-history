#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
py="$(../scripts/venv-python)"
swift build --product computer-history-agent
agent="$(swift build --show-bin-path)/computer-history-agent"
cd ..
CAPTURE_AGENT_BINARY="$agent" exec "$py" -m pytest -q tests/test_capture_e2e.py "$@"
