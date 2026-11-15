#!/usr/bin/env bash
# Build the LLVM pass plugin itself with ASan+UBSan and exercise the
# policy/control-flow suites with the sanitizer runtime loaded into `opt`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${AEGIS_SANITIZER_BUILD:-$REPO_ROOT/build-sanitize}"
LLVM_DIR="${LLVM_DIR:-/usr/lib/llvm-23/lib/cmake/llvm}"
CLANG="${CLANG:-clang++-23}"

cmake -S "$REPO_ROOT" -B "$BUILD_DIR" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_COMPILER="$CLANG" \
  -DLLVM_DIR="$LLVM_DIR" \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer" \
  -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address,undefined"
cmake --build "$BUILD_DIR" --target AegisPass -j2

PLUGIN="$BUILD_DIR/lib/AegisPass.so"
WORK="$BUILD_DIR/sanitizer-smoke"
rm -rf "$WORK"
mkdir -p "$WORK"

clang++-23 -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  "$REPO_ROOT/examples/demo.cpp" -o "$WORK/demo.ll"

ASAN_RUNTIME="$("$CLANG" -print-file-name=libclang_rt.asan-x86_64.so)"
export LD_PRELOAD="$ASAN_RUNTIME${LD_PRELOAD:+:$LD_PRELOAD}"
export ASAN_OPTIONS="detect_leaks=0:abort_on_error=1:halt_on_error=1:symbolize=0:verify_asan_link_order=0"
export UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"

opt-23 -load-pass-plugin="$PLUGIN" \
  -passes="aegis-policy<policy=$REPO_ROOT/examples/aegis-policy.json>,aegis-lint" \
  -disable-output "$WORK/demo.ll" 2> "$WORK/lint.log"
grep -q "eligible=yes" "$WORK/lint.log"

if opt-23 -load-pass-plugin="$PLUGIN" \
    -passes="aegis-policy<policy=$REPO_ROOT/tests/policy/policies/malformed.json>" \
    -disable-output "$WORK/demo.ll" 2> "$WORK/malformed.log"; then
  echo "sanitizer smoke: malformed policy unexpectedly passed" >&2
  exit 1
fi
grep -q "invalid JSON" "$WORK/malformed.log"

sed 's/"level": 1/"level": 3/' \
  "$REPO_ROOT/examples/aegis-policy.json" > "$WORK/level3.json"
opt-23 -load-pass-plugin="$PLUGIN" \
  -passes="aegis-policy<policy=$WORK/level3.json>,aegis-decoys,aegis-cff,default<O2>,aegis-verify" \
  -disable-output "$WORK/demo.ll" 2> "$WORK/level3.log"
grep -q "\[aegis-verify\] OK" "$WORK/level3.log"

if opt-23 -load-pass-plugin="$PLUGIN" \
    -passes="aegis-policy<policy=$WORK/level3.json>,default<O2>,aegis-verify" \
    -disable-output "$WORK/demo.ll" 2> "$WORK/fail-closed.log"; then
  echo "sanitizer smoke: verify gate unexpectedly passed" >&2
  exit 1
fi
grep -q "protection degraded" "$WORK/fail-closed.log"

echo "plugin sanitizer checks: OK"
