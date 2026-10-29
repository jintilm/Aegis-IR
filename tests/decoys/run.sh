#!/usr/bin/env bash
# End-to-end tests for the decoy transform and its post-optimization gate
# (stage 4).
#
# Usage: run.sh <path-to-AegisPass.so>
# Requires clang++-23 and opt-23 in PATH (or set CLANG / OPT env vars).

set -u

PLUGIN="${1:?usage: run.sh <path-to-AegisPass.so>}"
CLANG="${CLANG:-clang++-23}"
OPT="${OPT:-opt-23}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY="$HERE/policies/decoy.json"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILED=0
pass_case() { printf 'PASS  %s\n' "$1"; }
fail_case() { printf 'FAIL  %s\n' "$1"; FAILED=1; }

# Frontend IR (-disable-llvm-passes) is required: a -O2 -emit-llvm module has
# already been inlined, so guarding there protects a dead copy of the function
# and the verify gate (correctly) fails the build. Optimization runs inside the
# opt pipeline, after the transform.
"$CLANG" -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  "$HERE/fixtures/decoy_target.cpp" -o "$TMP/input.ll" \
  || { echo "cannot compile fixture"; exit 1; }

PIPELINE="aegis-policy<policy=$POLICY>,aegis-decoys,default<O2>,aegis-verify"

# run_opt <output.ll> <passes> [input]; sets OUT and CODE
run_opt() {
  local out="$1" passes="$2" input="${3:-$TMP/input.ll}"
  OUT="$("$OPT" -load-pass-plugin="$PLUGIN" -passes="$passes" \
    "$input" -S -o "$out" 2>&1)"
  CODE=$?
}

echo "== aegis-decoys: happy path through -O2 =="
run_opt "$TMP/prot.ll" "$PIPELINE"
if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q '\[aegis-verify\] OK'; then
  pass_case "pipeline builds and verifier passes"
else
  fail_case "pipeline builds and verifier passes (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -20
fi

DECOY_FNS="$(grep -c '^define .*!aegis.decoy.fn' "$TMP/prot.ll" 2>/dev/null || true)"
if [ "${DECOY_FNS:-0}" -ge 4 ]; then
  pass_case "decoy functions survive -O2 ($DECOY_FNS present)"
else
  fail_case "decoy functions survive -O2 (got ${DECOY_FNS:-0})"
fi

DECOY_STRS="$(grep -c '!aegis.decoy.str' "$TMP/prot.ll" 2>/dev/null || true)"
if [ "${DECOY_STRS:-0}" -ge 4 ]; then
  pass_case "decoy strings survive -O2 ($DECOY_STRS present)"
else
  fail_case "decoy strings survive -O2 (got ${DECOY_STRS:-0})"
fi

if grep -q 'load volatile i32, ptr @__aegis.guard' "$TMP/prot.ll"; then
  pass_case "volatile guard load present"
else
  fail_case "volatile guard load present"
fi

# The module must still pass LLVM's own verifier.
if "$OPT" -passes=verify -disable-output "$TMP/prot.ll" 2>/dev/null; then
  pass_case "protected IR passes llvm verifier"
else
  fail_case "protected IR passes llvm verifier"
fi

echo "== aegis-decoys: level-0 functions stay untouched =="
if printf '%s\n' "$OUT" | grep -q 'guarded functions: 1/1'; then
  pass_case "exactly one function guarded"
else
  fail_case "exactly one function guarded"
  printf '%s\n' "$OUT" | grep 'guarded functions' | sed 's/^/      /'
fi
# classify() must not contain a guard load: count guard loads inside it.
CLASSIFY_BODY="$(sed -n '/^define .*@classify(/,/^}/p' "$TMP/prot.ll")"
if printf '%s\n' "$CLASSIFY_BODY" | grep -q '__aegis.guard'; then
  fail_case "level-0 function has no guard"
else
  pass_case "level-0 function has no guard"
fi
if printf '%s\n' "$CLASSIFY_BODY" | grep -qE '@(lic_|kdf_|attest_|drm_|cfg_|sig_|tok_|hw_|crl_|kms_|env_)'; then
  fail_case "level-0 function has no decoy call"
else
  pass_case "level-0 function has no decoy call"
fi

echo "== aegis-verify: gate rejects degraded builds =="
run_opt "$TMP/nodecoy.ll" "aegis-policy<policy=$POLICY>,default<O2>,aegis-verify"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -q 'protection degraded'; then
  pass_case "skipping aegis-decoys fails the verify gate"
else
  fail_case "skipping aegis-decoys fails the verify gate (exit=$CODE)"
fi

# Simulate a seed drift between the transform and the gate by rewriting the
# module flag in the protected IR before re-running only the verifier.
sed 's/\("aegis.seed", i32 \)4242/\19999/' "$TMP/prot.ll" > "$TMP/seed_drift.ll"
run_opt /dev/null "aegis-verify" "$TMP/seed_drift.ll"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -q 'decoy function missing'; then
  pass_case "seed mismatch fails the verify gate"
else
  fail_case "seed mismatch fails the verify gate (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -10
fi

echo "== aegis-decoys: determinism =="
run_opt "$TMP/again.ll" "$PIPELINE"
if [ "$CODE" -eq 0 ] && cmp -s "$TMP/prot.ll" "$TMP/again.ll"; then
  pass_case "same seed reproduces byte-identical IR"
else
  fail_case "same seed reproduces byte-identical IR"
fi

echo "== aegis-decoys: plan depends on the seed =="
sed 's/4242/777/' "$POLICY" > "$TMP/policy777.json"
"$OPT" -load-pass-plugin="$PLUGIN" \
  -passes="aegis-policy<policy=$TMP/policy777.json>,aegis-decoys,default<O2>" \
  "$TMP/input.ll" -S -o "$TMP/seed777.ll" 2>/dev/null
if grep -q '__aegis' "$TMP/seed777.ll" && ! cmp -s "$TMP/prot.ll" "$TMP/seed777.ll"; then
  pass_case "different seed yields a different module"
else
  fail_case "different seed yields a different module"
fi

echo "== aegis-decoys: inlining keeps the branch =="
"$CLANG" -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  "$HERE/fixtures/inline_target.cpp" -o "$TMP/inline_raw.ll" \
  || fail_case "compile inlining fixture"
# Make the leaf internal so -O2 actually inlines it into the externally visible
# root; otherwise it stays a standalone definition and nothing is exercised.
sed 's/^define dso_local \(.*@leaf_check(\)/define internal \1/' \
  "$TMP/inline_raw.ll" > "$TMP/inline.ll"
run_opt "$TMP/inline.prot.ll" \
  "aegis-policy<policy=$HERE/policies/inline.json>,aegis-decoys,default<O2>,aegis-verify" \
  "$TMP/inline.ll"
if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q '1 inlined away'; then
  pass_case "inlined function is reported, gate still passes"
else
  # Not every LLVM version inlines this fixture; the gate must pass either way.
  if [ "$CODE" -eq 0 ]; then
    pass_case "inline fixture passes the gate (not inlined on this LLVM)"
  else
    fail_case "inline fixture passes the gate (exit=$CODE)"
    printf '%s\n' "$OUT" | sed 's/^/      /' | tail -10
  fi
fi
# Whatever happened, the guard branch must exist somewhere in the module.
if grep -q 'load volatile i32, ptr @__aegis.guard' "$TMP/inline.prot.ll" 2>/dev/null; then
  pass_case "guard branch survives inlining"
else
  fail_case "guard branch survives inlining"
fi

# Negative control: strip the guard load from the protected IR and delete the
# function bodies the flag names, then the gate must refuse the module. This
# simulates an optimizer that erased the branch instead of propagating it.
sed 's/load volatile i32, ptr @__aegis.guard/load i32, ptr @__aegis.guard/' \
  "$TMP/inline.prot.ll" > "$TMP/erased.ll"
run_opt /dev/null "aegis-verify" "$TMP/erased.ll"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -q 'guard load'; then
  pass_case "non-volatile guard load fails the gate"
else
  fail_case "non-volatile guard load fails the gate (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -10
fi

echo "== aegis-decoys: higher levels are still guarded here =="
# Level 2/3 add their own transforms; the entry guard is still this pass's job.
sed 's/"level": 1/"level": 3/' "$POLICY" > "$TMP/level3.json"
run_opt "$TMP/level3.ll" \
  "aegis-policy<policy=$TMP/level3.json>,aegis-decoys" "$TMP/input.ll"
if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q 'guarded=1'; then
  pass_case "level-3 selection is guarded by aegis-decoys"
else
  fail_case "level-3 selection is guarded by aegis-decoys (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -8
fi

# A function built at -O0 carries optnone; the transform cannot touch it, and
# silently skipping it would ship a binary the policy claims is protected.
"$CLANG" -O0 -S -emit-llvm "$HERE/fixtures/decoy_target.cpp" \
  -o "$TMP/optnone.ll" || fail_case "compile -O0 fixture"
run_opt /dev/null "aegis-policy<policy=$POLICY>,aegis-decoys" "$TMP/optnone.ll"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -q 'cannot protect'; then
  pass_case "ineligible selected function fails the build"
else
  fail_case "ineligible selected function fails the build (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -8
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo "aegis-decoys tests: FAILED"
  exit 1
fi
echo "aegis-decoys tests: OK"
