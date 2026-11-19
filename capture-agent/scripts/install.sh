#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
app="$HOME/Applications/ComputerHistoryAgent.app"
agent="$app/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' Bundle/Info.plist)"
job="gui/$(id -u)/$(/usr/libexec/PlistBuddy -c 'Print :Label' Bundle/LaunchAgent.plist)"

running() {
  for _ in 1 2 3 4 5 6; do
    launchctl print "$job" 2>/dev/null | grep -q 'state = running' && return 0
    sleep 0.5
  done
  return 1
}

scripts/build.sh
if [ -x "$agent" ]; then
  "$agent" uninstall
fi
mkdir -p "$HOME/Applications"
rm -rf "$app"
ditto .build/ComputerHistoryAgent.app "$app"
"$agent" install

for _ in 1 2 3; do
  if running; then
    echo "Running from $app"
    exit 0
  fi
  # Forces the failed launch that makes macOS replace the old binary's launch constraint.
  launchctl kickstart "$job" >/dev/null 2>&1 || true
  sleep 1
  "$agent" uninstall >/dev/null
  "$agent" install >/dev/null
done
echo "The agent is registered but did not start. Check: launchctl print $job" >&2
exit 1
