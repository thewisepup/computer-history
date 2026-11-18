#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
identity="${CODESIGN_IDENTITY:-Computer History Code Signing}"
executable="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' Bundle/Info.plist)"
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' Bundle/Info.plist)"
app=.build/ComputerHistoryAgent.app

swift build -c release --product "$executable"
bin="$(swift build -c release --show-bin-path)"

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Library/LaunchAgents"
cp Bundle/Info.plist "$app/Contents/Info.plist"
cp Bundle/LaunchAgent.plist "$app/Contents/Library/LaunchAgents/$bundle_id.plist"
cp "$bin/$executable" "$app/Contents/MacOS/$executable"

codesign --force --options runtime --timestamp=none --sign "$identity" "$app"
codesign --verify --deep --strict "$app"
echo "Built and signed $PWD/$app"
