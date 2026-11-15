#!/usr/bin/env bash
# Run Clang's path-sensitive analyzer over the plugin implementation.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLANG="${CLANG:-clang++-23}"
CXXFLAGS="$("${LLVM_CONFIG:-llvm-config-23}" --cxxflags)"
LOG_DIR="${AEGIS_ANALYZER_LOG_DIR:-$REPO_ROOT/build-analyzer}"
mkdir -p "$LOG_DIR"

failed=0
for source in "$REPO_ROOT"/lib/*.cpp; do
  name="$(basename "$source")"
  log="$LOG_DIR/${name%.cpp}.log"
  echo "== analyze $name"
  if ! "$CLANG" --analyze -std=c++17 $CXXFLAGS \
      -I"$REPO_ROOT/include" -I"$REPO_ROOT/lib" \
      "$source" -Xanalyzer -analyzer-output=text 2> "$log"; then
    cat "$log" >&2
    failed=1
    continue
  fi
  if grep -q "warning:" "$log"; then
    cat "$log" >&2
    failed=1
  fi
done

[ "$failed" -eq 0 ] || exit 1
echo "clang static analyzer: OK"
