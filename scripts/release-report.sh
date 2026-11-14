#!/usr/bin/env bash
# Reproduce the release validation report.
#
# Runs, inside the pinned container:
#   1. the full CTest suite,
#   2. the differential matrix (writes build/differential-report.json),
#   3. Aegis-Bench with the ground-truth replay and a negative control,
# and copies the machine-written artifacts into docs/reports/<name>/ together
# with a header explaining what they do and do not show.
#
# Usage: scripts/release-report.sh [output-name]
#
# This produces a *reproducibility* artifact, not an effectiveness claim: the
# adapters are offline test doubles, so the cost columns are n/a by
# construction. See docs/reports/README.md.

set -euo pipefail

NAME="${1:-harness-validation}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/docs/reports/$NAME"
WORK="$REPO_ROOT/bench-out/release-$NAME"
IMAGE="${AEGIS_IMAGE:-aegis-ir-dev}"
if command -v cygpath >/dev/null 2>&1; then
  MOUNT_ROOT="$(cygpath -w "$REPO_ROOT")"
else
  MOUNT_ROOT="$REPO_ROOT"
fi
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "error: working tree is dirty; commit before generating a report" >&2
  exit 2
fi
COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"

rm -rf "$WORK"
mkdir -p "$WORK"

if [ "${AEGIS_IN_CONTAINER:-0}" = "1" ]; then
  # Windows hosts without a native bash can execute the whole script in the
  # pinned container once, with the repository already mounted at /src.
  run_in_container() {
    bash -c "$1"
  }
else
  run_in_container() {
    MSYS_NO_PATHCONV=1 docker run --rm \
      --cap-add SYS_ADMIN --cap-add NET_ADMIN \
      -v "$MOUNT_ROOT:/src" -w /src \
      "$IMAGE" bash -c "$1"
  }
fi

echo "== build + test suite ==" | tee "$WORK/ctest.log"
run_in_container '
set -e
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR=/usr/lib/llvm-23/lib/cmake/llvm
cmake --build build -j
cd build && ctest --output-on-failure
' 2>&1 | tee -a "$WORK/ctest.log"

echo "== protection engineering scorecard ==" | tee "$WORK/scorecard.log"
run_in_container '
set -e
cd tools/aegis-bench
python3 -m aegis_bench scorecard \
  --differential ../../build/differential-report.json \
  --budgets ../../experiments/protection-budgets.json \
  --out ../../build/scorecard
' 2>&1 | tee -a "$WORK/scorecard.log"
rm -rf "$WORK/scorecard"
cp -r "$REPO_ROOT/build/scorecard" "$WORK/scorecard"

echo "== representative protection scorecard ==" \
  | tee "$WORK/scorecard-representative.log"
run_in_container '
set -e
cd tools/aegis-bench
python3 -m aegis_bench scorecard \
  --differential ../../build/representative-differential-report.json \
  --budgets ../../experiments/protection-budgets-representative.json \
  --out ../../build/scorecard-representative
' 2>&1 | tee -a "$WORK/scorecard-representative.log"
rm -rf "$WORK/scorecard-representative"
cp -r "$REPO_ROOT/build/scorecard-representative" \
  "$WORK/scorecard-representative"

echo "== bench: ground-truth replay (positive control) =="
echo "== bench: stub (negative control) =="
# Both runs write to /tmp inside the container; the worktree is touched only
# after they finish. Writing one report before the other run starts would make
# the second run stamp "dirty: yes" because of the first run's own output.
run_in_container "
set -e
cd tools/aegis-bench
bench() {
  python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \\
    --task rolling-token-v2 --adapter \"\$1\" --profile baseline \\
    --artifact-cache /tmp/aegis-bench-artifacts --out \"/tmp/bench-\$2\"
}
bench ground-truth ground-truth > /tmp/ground-truth.log 2>&1 || true
grep -q '^\[PASS\]' /tmp/ground-truth.log
bench stub stub > /tmp/stub.log 2>&1 || true
grep -q '^\[FAIL\]' /tmp/stub.log
cp /tmp/ground-truth.log /src/bench-out/release-$NAME/bench-ground-truth.log
cp /tmp/stub.log /src/bench-out/release-$NAME/bench-stub.log
rm -rf /src/bench-out/release-$NAME/bench-ground-truth \
  /src/bench-out/release-$NAME/bench-stub
cp -r /tmp/bench-ground-truth /tmp/bench-stub /src/bench-out/release-$NAME/
cat /tmp/ground-truth.log /tmp/stub.log
"

echo "== bench: campaign, resume and audit =="
run_in_container "
set -e
cd tools/aegis-bench
CFG=/src/experiments/offline-smoke.json
OUT=/tmp/bench-campaign
rm -rf \"\$OUT\"
python3 -m aegis_bench campaign --config \"\$CFG\" --out \"\$OUT\" \
  > /tmp/campaign.log 2>&1
python3 -m aegis_bench campaign --config \"\$CFG\" --out \"\$OUT\" \
  >> /tmp/campaign.log 2>&1
python3 -m aegis_bench audit \"\$OUT\" --experiment \"\$CFG\" --json \
  > /tmp/campaign-audit.json
rm -f \"\$OUT/.campaign.lock\"
rm -rf /src/bench-out/release-$NAME/bench-campaign
cp -r \"\$OUT\" /src/bench-out/release-$NAME/bench-campaign
cp /tmp/campaign.log /src/bench-out/release-$NAME/bench-campaign.log
cp /tmp/campaign-audit.json /src/bench-out/release-$NAME/bench-campaign-audit.json
cat /tmp/campaign.log
cat /tmp/campaign-audit.json
"

echo "== bench: process-sandbox campaign =="
run_in_container "
set -e
cd tools/aegis-bench
CFG=/src/experiments/process-smoke.json
OUT=/tmp/bench-process-campaign
rm -rf \"\$OUT\"
python3 -m aegis_bench campaign --config \"\$CFG\" --out \"\$OUT\" \
  > /tmp/process-campaign.log 2>&1
python3 -m aegis_bench audit \"\$OUT\" --experiment \"\$CFG\" --json \
  > /tmp/process-campaign-audit.json
rm -f \"\$OUT/.campaign.lock\"
rm -rf /src/bench-out/release-$NAME/bench-process-campaign
cp -r \"\$OUT\" /src/bench-out/release-$NAME/bench-process-campaign
cp /tmp/process-campaign.log \
  /src/bench-out/release-$NAME/bench-process-campaign.log
cp /tmp/process-campaign-audit.json \
  /src/bench-out/release-$NAME/bench-process-campaign-audit.json
cat /tmp/process-campaign.log
cat /tmp/process-campaign-audit.json
"

echo "== bench: network-namespace campaign =="
run_in_container "
set -e
cd tools/aegis-bench
CFG=/src/experiments/netns-smoke.json
OUT=/tmp/bench-netns-campaign
rm -rf \"\$OUT\"
python3 -m aegis_bench campaign --config \"\$CFG\" --out \"\$OUT\" \
  > /tmp/netns-campaign.log 2>&1
python3 -m aegis_bench audit \"\$OUT\" --experiment \"\$CFG\" --json \
  > /tmp/netns-campaign-audit.json
rm -f \"\$OUT/.campaign.lock\"
rm -rf /src/bench-out/release-$NAME/bench-netns-campaign
cp -r \"\$OUT\" /src/bench-out/release-$NAME/bench-netns-campaign
cp /tmp/netns-campaign.log \
  /src/bench-out/release-$NAME/bench-netns-campaign.log
cp /tmp/netns-campaign-audit.json \
  /src/bench-out/release-$NAME/bench-netns-campaign-audit.json
cat /tmp/netns-campaign.log
cat /tmp/netns-campaign-audit.json
"

mkdir -p "$OUT"
cp -r "$WORK"/. "$OUT"/
cp "$REPO_ROOT/build/differential-report.json" "$OUT/"
cp "$REPO_ROOT/build/representative-differential-report.json" "$OUT/"
find "$OUT" -type f -name '*.log' -exec \
  sed -E -i 's/[[:space:]]+$//' {} +

cat > "$OUT/README.md" <<EOF
# Report: $NAME

Generated by \`scripts/release-report.sh\` from source commit
\`$COMMIT\` (dirty: no). Reproduce with:

\`\`\`bash
scripts/release-report.sh $NAME
\`\`\`

## What this shows

- all 8/8 CTest targets pass in the pinned container (\`ctest.log\`);
- task schema v4 is validated with an explicit \`core\` or \`exploratory\` tier
  in every public manifest; the set contains twelve tasks, eleven of them
  binary-recovery tasks;
- the fixture differential matrix runs eight build profiles (levels 0/1/2/3)
  over the same corpus with zero output mismatches and zero sanitizer reports
  (\`differential-report.json\`, including \`.text\`/\`.data\` totals and p95
  wall time per profile);
- the representative differential matrix runs baseline, standard, research and
  flattened profiles over a larger algorithm workload with at least 1 MiB of
  work per invocation (\`representative-differential-report.json\`);
- both deterministic protection scorecards enforce correctness, \`.text\`,
  p95 and build-time budgets. Build time is the median of three independent
  clean builds in each arm (\`scorecard/scorecard.md\`,
  \`scorecard/scorecard.json\`, \`scorecard-representative/scorecard.md\`,
  \`scorecard-representative/scorecard.json\`);
- Aegis-Bench builds \`rolling-token-v2\`'s stripped baseline probe and scores
  a known-correct solution at 100% and a compiling-but-wrong one at ~0%
  (\`bench-ground-truth/\`, \`bench-stub/\`), which validates the grader end to
  end; CTest checks all twelve public manifests and builds every protected
  artifact profile for the eight tasks added in the v0.2/v0.3 families,
  including parser, state-machine, ring-buffer, graph-routing, delta-ledger,
  S-box, bit-matrix and packet-framing families;
- the offline campaign writes a row, checkpoints it, resumes without rerunning
  the cell, and passes the campaign-aware audit
  (\`bench-campaign/\`, \`bench-campaign-audit.json\`);
- the process-sandbox campaign runs a fresh adapter worker with the loopback
  broker and Linux Landlock filesystem/TCP rules, and passes its audit
  (\`bench-process-campaign/\`, \`bench-process-campaign-audit.json\`);
- the network-namespace campaign proves the worker cannot connect directly to
  a host listener, while the per-cell Unix-socket bridge still reaches the
  harness broker and retains its counters
  (\`bench-netns-campaign/\`, \`bench-netns-campaign-audit.json\`).

## What this does **not** show

- **No effectiveness claim.** The adapters are offline test doubles. No model
  was involved, so the token and tool-call columns are \`n/a\` by construction.
  Protection effectiveness against any attacker class is unmeasured and is
  not claimed anywhere in this repository.
- No production-performance claim. The small fixture is a regression tripwire.
  The representative suite adds sustained algorithm work, but both workloads
  are synthetic and self-authored. Neither scorecard is a production
  benchmark.
- No N=5 claim for N=1 screening calibration. Only
  \`packed-record-v1\` has N=5 records for both pilot models; the other
  populated binary-task calibration records are screening data and the
  remaining tasks are explicitly uncalibrated.

Claims that do exist for this stage are in \`docs/claims-ledger.md\`; each
entry names its own validation or pilot artifact.
EOF

echo
echo "artifacts written to $OUT"
find "$OUT" -maxdepth 2 -type f | sort
