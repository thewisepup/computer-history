#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
app="$HOME/Applications/ComputerHistoryAgent.app"
agent="$app/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' Bundle/Info.plist)"

if [ -x "$agent" ]; then
  "$agent" uninstall
fi
rm -rf "$app"
echo "Removed $app"
