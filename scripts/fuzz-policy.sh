#!/usr/bin/env bash
# Build and run the policy parser under libFuzzer with ASan+UBSan.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${AEGIS_FUZZ_BUILD:-$REPO_ROOT/build-fuzz}"
LLVM_DIR="${LLVM_DIR:-/usr/lib/llvm-23/lib/cmake/llvm}"
CLANG="${CLANG:-clang++-23}"
RUNS="${AEGIS_FUZZ_RUNS:-2000}"

cmake -S "$REPO_ROOT" -B "$BUILD_DIR" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_COMPILER="$CLANG" \
  -DLLVM_DIR="$LLVM_DIR" \
  -DAEGIS_BUILD_FUZZERS=ON
cmake --build "$BUILD_DIR" --target AegisPolicyFuzz -j2

export ASAN_OPTIONS="detect_leaks=0:abort_on_error=1:halt_on_error=1"
export UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"

CORPUS="$(mktemp -d)"
trap 'rm -rf "$CORPUS"' EXIT
cp "$REPO_ROOT"/tests/policy/policies/*.json "$CORPUS"/

"$BUILD_DIR/lib/AegisPolicyFuzz" \
  -runs="$RUNS" \
  "$CORPUS"

echo "policy parser fuzz: OK ($RUNS runs)"
