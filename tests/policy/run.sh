#!/usr/bin/env bash
# End-to-end tests for the aegis-policy pass (stage 2).
#
# Usage: run.sh <path-to-AegisPass.so>
# Requires clang++-23 and opt-23 in PATH (or set CLANG / OPT env vars).

set -u

PLUGIN="${1:?usage: run.sh <path-to-AegisPass.so>}"
CLANG="${CLANG:-clang++-23}"
OPT="${OPT:-opt-23}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILED=0
pass_case() { printf 'PASS  %s\n' "$1"; }
fail_case() { printf 'FAIL  %s\n' "$1"; FAILED=1; }

"$CLANG" -O0 -S -emit-llvm "$HERE/fixtures/selection.cpp" -o "$TMP/input.ll" \
  || { echo "cannot compile fixture"; exit 1; }

# run_policy <policy-file>; sets OUT (combined output) and CODE (exit status)
run_policy() {
  OUT="$("$OPT" -load-pass-plugin="$PLUGIN" \
    -passes="aegis-policy<policy=$1>" -disable-output "$TMP/input.ll" 2>&1)"
  CODE=$?
}

expect_ok() { # name policy-file
  run_policy "$2"
  if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q 'summary: matched=1'; then
    pass_case "$1"
  else
    fail_case "$1 (exit=$CODE)"
    printf '%s\n' "$OUT" | sed 's/^/      /'
  fi
}

expect_fail() { # name policy-file pattern
  run_policy "$2"
  if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -qE "$3"; then
    pass_case "$1"
  else
    fail_case "$1 (exit=$CODE)"
    printf '%s\n' "$OUT" | sed 's/^/      /'
  fi
}

echo "== aegis-policy: happy path =="
expect_ok "select by mangled name" "$HERE/policies/ok.json"
if printf '%s\n' "$OUT" | grep -qF 'select _Z15transform_valuei (transform_value(int)) level=1 reason="benchmark fixture"'; then
  pass_case "selection report line"
else
  fail_case "selection report line"
fi

echo "== aegis-policy: applied to IR =="
"$OPT" -load-pass-plugin="$PLUGIN" -passes="aegis-policy<policy=$HERE/policies/ok.json>" \
  -S "$TMP/input.ll" -o "$TMP/out.ll" 2>/dev/null
COUNT="$(grep -o '"aegis.level"' "$TMP/out.ll" | wc -l | tr -d ' ')"
if [ "$COUNT" = "1" ]; then pass_case "exactly one annotated function"; else fail_case "exactly one annotated function (got $COUNT)"; fi
if grep -q 'aegis.profile' "$TMP/out.ll"; then pass_case "profile module flag present"; else fail_case "profile module flag present"; fi
if grep -q 'aegis.seed' "$TMP/out.ll"; then pass_case "seed module flag present"; else fail_case "seed module flag present"; fi
if grep -qF '"aegis.level"="1"' "$TMP/out.ll"; then pass_case "level attribute value"; else fail_case "level attribute value"; fi

echo "== aegis-policy: error cases =="
expect_fail "unknown function fails the build" "$HERE/policies/missing.json" 'not found'
expect_fail "level out of range fails the build" "$HERE/policies/bad_level.json" 'level must be in'
expect_fail "malformed JSON fails the build" "$HERE/policies/malformed.json" 'invalid JSON'
expect_fail "duplicate entries fail the build" "$HERE/policies/dup.json" 'duplicate'
expect_fail "declaration-only match fails the build" "$HERE/policies/decl_only.json" 'declaration'

echo "== aegis-policy: demangled fallback =="
expect_ok "select by bare demangled name" "$HERE/policies/demangled.json"
if printf '%s\n' "$OUT" | grep -qF '(matched by demangled name)'; then
  pass_case "demangled-match note reported"
else
  fail_case "demangled-match note reported"
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo "aegis-policy tests: FAILED"
  exit 1
fi
echo "aegis-policy tests: OK"