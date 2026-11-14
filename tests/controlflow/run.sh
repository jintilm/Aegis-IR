#!/usr/bin/env bash
# End-to-end tests for the level 2/3 control-flow transforms and their gate.
#
# Usage: run.sh <path-to-AegisPass.so>
# Requires clang++-23 and opt-23 in PATH (or set CLANG / OPT env vars).

set -u

PLUGIN="${1:?usage: run.sh <path-to-AegisPass.so>}"
CLANG="${CLANG:-clang++-23}"
OPT="${OPT:-opt-23}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POL2="$HERE/policies/level2.json"
POL3="$HERE/policies/level3.json"
POLBAD="$HERE/policies/ineligible.json"
POLPHI="$HERE/policies/phi.json"
POLSTATELESS="$HERE/policies/stateless.json"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILED=0
pass_case() { printf 'PASS  %s\n' "$1"; }
fail_case() { printf 'FAIL  %s\n' "$1"; FAILED=1; }
has_text() { grep -Fq -- "$1" <<< "$2"; }

# run_opt <output.ll|/dev/null> <passes> [input]; sets OUT and CODE
run_opt() {
  local out="$1" passes="$2" input="${3:-$TMP/input.ll}"
  OUT="$("$OPT" -load-pass-plugin="$PLUGIN" -passes="$passes" \
    "$input" -S -o "$out" 2>&1)"
  CODE=$?
}

# build_exe <name> <ir>: compiles the protected library and the shared driver.
build_exe() {
  "$CLANG" -O2 -c "$2" -o "$TMP/$1.o" 2>"$TMP/$1.build" || return 1
  "$CLANG" -O2 "$TMP/$1.o" "$TMP/driver.o" -o "$TMP/$1" 2>>"$TMP/$1.build"
}

"$CLANG" -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  "$HERE/fixtures/cf_target.cpp" -I "$HERE/fixtures" -o "$TMP/input.ll" \
  || { echo "cannot compile fixture"; exit 1; }
"$CLANG" -O2 -c "$HERE/fixtures/driver.cpp" -I "$HERE/fixtures" \
  -o "$TMP/driver.o" || { echo "cannot compile driver"; exit 1; }

# Baseline: same frontend IR through the same optimizer, no Aegis passes.
"$OPT" -passes='default<O2>' "$TMP/input.ll" -S -o "$TMP/base.ll" 2>/dev/null
build_exe base "$TMP/base.ll" || { echo "cannot build baseline"; exit 1; }
BASE_OUT="$("$TMP/base")"
BASE_CODE=$?

PIPE2="aegis-policy<policy=$POL2>,aegis-decoys,aegis-cff,default<O2>,aegis-verify"
PIPE3="aegis-policy<policy=$POL3>,aegis-decoys,aegis-cff,default<O2>,aegis-verify"

echo "== lint: policy selection before transforms =="
run_opt /dev/null "aegis-policy<policy=$POL3>,aegis-lint"
if [ "$CODE" -eq 0 ] && has_text 'eligible=yes' "$OUT" && \
   has_text 'advisory=protect-and-measure' "$OUT" && \
   has_text '[aegis-lint] summary:' "$OUT"; then
  pass_case "lint reports eligible level-3 selections"
else
  fail_case "lint reports eligible level-3 selections (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -20
fi
run_opt /dev/null "aegis-policy<policy=$POLBAD>,aegis-lint"
if [ "$CODE" -eq 0 ] && has_text 'eligible=no' "$OUT" && \
   has_text 'indirectbr' "$OUT" && \
   has_text 'advisory=rewrite-computed-goto-or-select-another-function' \
     "$OUT"; then
  pass_case "lint names the flattening-ineligible construct and repair"
else
  fail_case "lint names the flattening-ineligible construct and repair (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -20
fi
run_opt /dev/null "aegis-policy<policy=$POLSTATELESS>,aegis-lint" \
  "$HERE/fixtures/stateless.ll"
if [ "$CODE" -eq 0 ] && has_text 'advisory=move-to-server' "$OUT" && \
   has_text 'move_to_server=1' "$OUT"; then
  pass_case "lint recommends server migration for a small stateless function"
else
  fail_case "lint recommends server migration for a small stateless function (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -20
fi

echo "== level 2: pipeline and structural survival =="
run_opt "$TMP/l2.ll" "$PIPE2"
if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q '\[aegis-verify\] OK'; then
  pass_case "level-2 pipeline builds and verifies"
else
  fail_case "level-2 pipeline builds and verifies (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -20
fi

SALT_LOADS="$(grep -c 'load volatile i32, ptr @__aegis.cff.salt' "$TMP/l2.ll" 2>/dev/null || true)"
if [ "${SALT_LOADS:-0}" -ge 6 ]; then
  pass_case "opaque-predicate salt loads survive -O2 ($SALT_LOADS)"
else
  fail_case "opaque-predicate salt loads survive -O2 (got ${SALT_LOADS:-0})"
fi
if grep -q '@__aegis.cff.salt = internal global i32 0' "$TMP/l2.ll"; then
  pass_case "salt global is internal and zero-initialised"
else
  fail_case "salt global is internal and zero-initialised"
fi
if grep -q 'aegis.state' "$TMP/l2.ll"; then
  fail_case "level 2 does not flatten (unexpected state slot)"
else
  pass_case "level 2 does not flatten (no state slot)"
fi
if "$OPT" -passes=verify -disable-output "$TMP/l2.ll" 2>/dev/null; then
  pass_case "level-2 IR passes llvm verifier"
else
  fail_case "level-2 IR passes llvm verifier"
fi

echo "== level 2: program semantics =="
if build_exe l2 "$TMP/l2.ll" && [ "$("$TMP/l2")" = "$BASE_OUT" ]; then
  pass_case "level-2 output matches baseline"
else
  fail_case "level-2 output matches baseline"
  printf '%s\n' "$("$TMP/l2" 2>&1)" | sed 's/^/      /'
fi

echo "== level 3: pipeline and state-machine survival =="
run_opt "$TMP/l3.ll" "$PIPE3"
if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q '\[aegis-verify\] OK'; then
  pass_case "level-3 pipeline builds and verifies"
else
  fail_case "level-3 pipeline builds and verifies (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -25
fi

STATE_SLOTS="$(grep -c '%aegis.state[0-9]* = alloca i32' "$TMP/l3.ll" 2>/dev/null || true)"
STATE_LOADS="$(grep -c 'load volatile i32, ptr %aegis.state' "$TMP/l3.ll" 2>/dev/null || true)"
STATE_STORES="$(grep -c 'store volatile i32 .*aegis.state' "$TMP/l3.ll" 2>/dev/null || true)"
DISPATCHES="$(grep -c 'switch i32 %aegis.keyed' "$TMP/l3.ll" 2>/dev/null || true)"
if [ "${STATE_SLOTS:-0}" -ge 6 ] && [ "${STATE_LOADS:-0}" -ge 6 ]; then
  pass_case "state slots and volatile loads survive -O2 ($STATE_SLOTS slots, $STATE_LOADS loads)"
else
  fail_case "state slots and volatile loads survive -O2 (slots=${STATE_SLOTS:-0}, loads=${STATE_LOADS:-0})"
fi
if [ "${STATE_STORES:-0}" -ge 6 ] && [ "${DISPATCHES:-0}" -ge 6 ]; then
  pass_case "volatile state stores and dispatchers survive -O2 ($STATE_STORES stores, $DISPATCHES switches)"
else
  fail_case "volatile state stores and dispatchers survive -O2 (stores=${STATE_STORES:-0}, switches=${DISPATCHES:-0})"
fi
if "$OPT" -passes=verify -disable-output "$TMP/l3.ll" 2>/dev/null; then
  pass_case "level-3 IR passes llvm verifier"
else
  fail_case "level-3 IR passes llvm verifier"
fi

echo "== level 3: program semantics =="
if build_exe l3 "$TMP/l3.ll" && [ "$("$TMP/l3")" = "$BASE_OUT" ]; then
  pass_case "level-3 output matches baseline"
else
  fail_case "level-3 output matches baseline"
  printf '%s\n' "$("$TMP/l3" 2>&1)" | sed 's/^/      /'
fi

echo "== determinism =="
run_opt "$TMP/l3.again.ll" "$PIPE3"
if [ "$CODE" -eq 0 ] && cmp -s "$TMP/l3.ll" "$TMP/l3.again.ll"; then
  pass_case "same seed reproduces byte-identical IR"
else
  fail_case "same seed reproduces byte-identical IR"
fi

echo "== PHI demotion =="
run_opt "$TMP/phi.ll" \
  "aegis-policy<policy=$POLPHI>,aegis-decoys,aegis-cff,default<O2>,aegis-verify" \
  "$HERE/fixtures/phi_loop.ll"
if [ "$CODE" -eq 0 ] && printf '%s\n' "$OUT" | grep -q '\[aegis-verify\] OK'; then
  pass_case "hand-written PHI function flattens and verifies"
else
  fail_case "hand-written PHI function flattens and verifies (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -20
fi
PHI_CODE=999
if "$CLANG" -O2 -x ir "$TMP/phi.ll" -o "$TMP/phi" 2>"$TMP/phi.build"; then
  "$TMP/phi"
  PHI_CODE=$?
fi
if [ "$PHI_CODE" -eq 45 ]; then
  pass_case "PHI function returns the baseline result (45)"
else
  fail_case "PHI function returns the baseline result (45, got $PHI_CODE)"
  sed 's/^/      /' "$TMP/phi.build" 2>/dev/null | tail -10
fi

echo "== gate: fail-closed controls =="
# 1. Flattening requested, aegis-cff skipped.
run_opt /dev/null \
  "aegis-policy<policy=$POL3>,aegis-decoys,default<O2>,aegis-verify"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -Eq 'never flattened|dispatch state slot'; then
  pass_case "skipping aegis-cff fails the verify gate"
else
  fail_case "skipping aegis-cff fails the verify gate (exit=$CODE)"
  printf '%s\n' "$OUT" | grep -E 'error|aegis-verify' | sed 's/^/      /' | tail -8
fi

# 2. aegis-cff without the decoy pass it builds on.
run_opt /dev/null "aegis-policy<policy=$POL3>,aegis-cff"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -Eq 'no decoy guard branch|guard global or decoy functions missing'; then
  pass_case "aegis-cff without aegis-decoys fails the build"
else
  fail_case "aegis-cff without aegis-decoys fails the build (exit=$CODE)"
  printf '%s\n' "$OUT" | grep -E 'aegis-cff|no decoy' | sed 's/^/      /' | tail -5
fi

# 3. Non-volatile state load: mem2reg could recover the CFG, gate must refuse.
sed 's/load volatile i32, ptr %aegis.state/load i32, ptr %aegis.state/' \
  "$TMP/l3.ll" > "$TMP/flat_erased.ll"
run_opt /dev/null "aegis-verify" "$TMP/flat_erased.ll"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -Eq 'dispatch state|state machine'; then
  pass_case "non-volatile state load fails the gate"
else
  fail_case "non-volatile state load fails the gate (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -8
fi

# 4. Non-volatile salt load: the opaque predicates are no longer opaque.
sed 's/load volatile i32, ptr @__aegis.cff.salt/load i32, ptr @__aegis.cff.salt/' \
  "$TMP/l3.ll" > "$TMP/salt_erased.ll"
run_opt /dev/null "aegis-verify" "$TMP/salt_erased.ll"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -q 'control-flow salt'; then
  pass_case "non-volatile salt load fails the gate"
else
  fail_case "non-volatile salt load fails the gate (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -8
fi

# 4b. Volatile state load kept, but the dispatcher switch is replaced by a
#     constant: the structural check must notice the state no longer selects
#     anything, even though the volatile access still exists.
sed 's/switch i32 %aegis.keyed, label %aegis.trap \[/switch i32 0, label %aegis.trap [/' \
  "$TMP/l3.ll" > "$TMP/dispatch_gone.ll"
run_opt /dev/null "aegis-verify" "$TMP/dispatch_gone.ll"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -Eq 'lost its dispatch|no longer selects'; then
  pass_case "dispatcher detached from state load fails the gate"
else
  fail_case "dispatcher detached from state load fails the gate (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -8
fi

# 4c. Level-2 bogus arms made live: the salt load and the branch survive, but
#     the dead arm now rejoins the real path, so the structural check must
#     reject the build.
python3 - "$TMP/l2.ll" "$TMP/bogus_gone.ll" <<'PYEOF'
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
label_re = re.compile(r'^([A-Za-z0-9_.]+):')
br_re = re.compile(r'^\s*br i1 .*label %([A-Za-z0-9_.]+), label %([A-Za-z0-9_.]+)')
out, skipping, changed = [], False, 0
for line in open(src, encoding='utf-8'):
    match = label_re.match(line)
    if match:
        skipping = match.group(1).startswith('aegis.bogus')
    if skipping:
        changed += 1
        continue
    br = br_re.match(line)
    if br and any(l.startswith('aegis.bogus') for l in br.groups()):
        keep = [l for l in br.groups() if not l.startswith('aegis.bogus')][0]
        out.append('  br label %' + keep + chr(10))
        changed += 1
        continue
    out.append(line)
open(dst, 'w', encoding='utf-8').writelines(out)
if not changed:
    sys.exit('no bogus edge found to remove')
PYEOF
run_opt /dev/null "aegis-verify" "$TMP/bogus_gone.ll"
if [ "$CODE" -ne 0 ] && printf '%s
' "$OUT" | grep -q 'opaque-predicate edge'; then
  pass_case "level-2 bogus arm made live fails the gate"
else
  fail_case "level-2 bogus arm made live fails the gate (exit=$CODE)"
  printf '%s
' "$OUT" | sed 's/^/      /' | tail -8
fi

# 5. Level 3 on a construct flattening cannot rewrite (indirectbr).
run_opt /dev/null "aegis-policy<policy=$POLBAD>,aegis-decoys,aegis-cff"
if [ "$CODE" -ne 0 ] && printf '%s\n' "$OUT" | grep -q 'indirectbr'; then
  pass_case "level-3 selection of indirectbr fails loudly"
else
  fail_case "level-3 selection of indirectbr fails loudly (exit=$CODE)"
  printf '%s\n' "$OUT" | sed 's/^/      /' | tail -8
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo "aegis-controlflow tests: FAILED"
  exit 1
fi
echo "aegis-controlflow tests: OK"
