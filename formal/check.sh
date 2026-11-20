#!/usr/bin/env bash
# Model-check formal/spool/SpoolHandoff.tla with TLC on each config.
#   formal/check.sh               every config except the on-request ones (about 2 minutes)
#   formal/check.sh --all         every config in formal/spool/, on-request ones too (about 6 minutes)
#   formal/check.sh one_ingest    one config, by name
# Exit 0 when every config gives its expected result (see EXPECT below).
# TLC's full output for each config lands in formal/spool/out/<config>.out.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
spool="$here/spool"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/computer-history/tla"

TLA_VERSION=1.7.4
TLA_URL="https://github.com/tlaplus/tlaplus/releases/download/v$TLA_VERSION/tla2tools.jar"
TLA_SHA=936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)
    JRE_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13.1%2B2/OpenJDK21U-jre_aarch64_mac_hotspot_21.0.13.1_2.tar.gz"
    JRE_SHA=848feb1906c7de79de4f8391636042193fbd46eff86e26299506c4656f62c260 ;;
  Darwin-x86_64)
    JRE_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_mac_hotspot_21.0.13_9.tar.gz"
    JRE_SHA=c909674b1c10c261b9a3fb7e9c0efebd303e33f88a4fe84be7135b5e2d711f89 ;;
  *) JRE_URL=""; JRE_SHA="" ;;
esac

# Configs left out unless named or --all is given.
ON_REQUEST=" two_ingests_steady_clock "

# Expected result per config: "pass", or "fail <Invariant>" for a known
# finding that the current code has (see .claude/skills/verify-spool-handoff).
expect() {
  case "$1" in
    one_ingest) echo "pass" ;;
    two_ingests) echo "fail NoLoss" ;;
    two_ingests_steady_clock) echo "pass" ;;
    *) echo "pass" ;;
  esac
}

fetch() { # url sha dest
  if [ -f "$3" ] && [ "$(shasum -a 256 "$3" | cut -d' ' -f1)" = "$2" ]; then return; fi
  mkdir -p "$(dirname "$3")"
  curl -fsSL "$1" -o "$3.tmp"
  local got; got="$(shasum -a 256 "$3.tmp" | cut -d' ' -f1)"
  if [ "$got" != "$2" ]; then rm -f "$3.tmp"; echo "checksum mismatch for $1" >&2; exit 2; fi
  mv "$3.tmp" "$3"
}

fetch "$TLA_URL" "$TLA_SHA" "$cache/tla2tools-$TLA_VERSION.jar"
jar="$cache/tla2tools-$TLA_VERSION.jar"

java="${JAVA:-}"
if [ -z "$java" ]; then
  if [ -n "$JRE_URL" ]; then
    jre="$cache/jre-${JRE_SHA:0:12}"
    if [ ! -x "$jre/bin/java" ]; then
      fetch "$JRE_URL" "$JRE_SHA" "$cache/jre.tar.gz"
      rm -rf "$jre.tmp" && mkdir -p "$jre.tmp"
      tar -xzf "$cache/jre.tar.gz" -C "$jre.tmp" --strip-components=1
      rm -rf "$jre" && mv "$jre.tmp/Contents/Home" "$jre" && rm -rf "$jre.tmp" "$cache/jre.tar.gz"
    fi
    java="$jre/bin/java"
  else
    java="java"
  fi
fi

all=0
configs=()
for arg in "$@"; do
  if [ "$arg" = "--all" ]; then all=1; else configs+=("$arg"); fi
done
if [ ${#configs[@]} -eq 0 ]; then
  for f in "$spool"/*.cfg; do
    name="$(basename "$f" .cfg)"
    case "$ON_REQUEST" in *" $name "*) [ "$all" = 1 ] || continue ;; esac
    configs+=("$name")
  done
fi

mkdir -p "$spool/out"
status=0
for name in "${configs[@]}"; do
  out="$spool/out/$name.out"
  meta="$(mktemp -d)"
  (cd "$spool" && "$java" -XX:+UseParallelGC -cp "$jar" tlc2.TLC \
      -workers auto -metadir "$meta" -config "$name.cfg" SpoolHandoff.tla) >"$out" 2>&1 || true
  rm -rf "$meta"
  if grep -q "Model checking completed. No error has been found." "$out"; then
    got="pass"
  elif inv="$(grep -o 'Invariant [A-Za-z]* is violated' "$out" | head -1 | cut -d' ' -f2)" && [ -n "$inv" ]; then
    got="fail $inv"
  else
    got="error"
  fi
  states="$(grep -o '[0-9,]* distinct states found' "$out" | tail -1 || true)"
  want="$(expect "$name")"
  if [ "$got" = "$want" ]; then
    echo "ok    $name: $got as expected ($states)"
  else
    echo "FAIL  $name: got '$got', expected '$want' (see $out)"
    status=1
  fi
done
exit $status
