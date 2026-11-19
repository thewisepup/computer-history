#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
developer="$(xcode-select -p)/Library/Developer"
if [ -d "$developer/Frameworks/Testing.framework" ]; then
  # Command Line Tools ship Swift Testing outside the search paths SwiftPM passes.
  exec swift test \
    -Xswiftc -F -Xswiftc "$developer/Frameworks" \
    -Xlinker -rpath -Xlinker "$developer/Frameworks" \
    -Xlinker -rpath -Xlinker "$developer/usr/lib" \
    "$@"
fi
exec swift test "$@"
