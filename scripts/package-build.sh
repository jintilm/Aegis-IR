#!/usr/bin/env bash
# Build and test inside the release toolchain environment. Kept separate from
# archive staging so the failure paths can be checked without compiling LLVM.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR=/usr/lib/llvm-23/lib/cmake/llvm >/dev/null
cmake --build build -j >/dev/null

if [ "${AEGIS_PACKAGE_SKIP_TESTS:-0}" = "1" ]; then
  echo "build OK; tests skipped for deterministic rebuild comparison"
  exit 0
fi

# Open the log independently: a failed redirection must stop the build before
# CTest, and must never be confused with a successful test command.
TEST_LOG="$REPO_ROOT/build/package-ctest.log"
exec 3>"$TEST_LOG"
if ctest --test-dir "$REPO_ROOT/build" --output-on-failure >&3 2>&1; then
  exec 3>&-
  echo "build + tests OK"
else
  test_status=$?
  exec 3>&-
  cat "$TEST_LOG"
  exit "$test_status"
fi
