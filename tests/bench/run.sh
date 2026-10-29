#!/usr/bin/env bash
# Aegis-Bench harness tests (offline; deterministic adapters only).
#
# Usage: run.sh <path-to-aegis-bench-root> <path-to-AegisPass.so>
# Requires python3, clang++-23 and opt-23 on PATH (set BENCH_CXX / BENCH_CLANG /
# BENCH_OPT to override). The plugin is required for the level>=1 artifact
# profiles; baseline needs only the compiler and opt.

set -eu
BENCH_ROOT="${1:?usage: run.sh <tools/aegis-bench> <AegisPass.so>}"
PLUGIN="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TASKS_ROOT="$REPO_ROOT/benchmarks/tasks-public"

[ -n "$PLUGIN" ] || { echo "error: plugin path is required for artifact tests" >&2; exit 2; }
export AEGIS_PLUGIN="$PLUGIN"

# Manifest hashes must match the committed files; a stale hash means someone
# edited a task without re-running `aegis-bench hash`.
(cd "$BENCH_ROOT" && python3 -m aegis_bench check --tasks-root "$TASKS_ROOT")

(cd "$BENCH_ROOT" && python3 -m unittest discover -s tests -v)

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

run_bench() { # <agent> <profile> <out-name> [extra args...]
  local agent="$1" profile="$2" name="$3"
  shift 3
  (cd "$BENCH_ROOT" && python3 -m aegis_bench run \
     --tasks-root "$TASKS_ROOT" --adapter "$agent" --profile "$profile" \
     --plugin "$PLUGIN" --out "$OUT/$name" "$@")
}

echo "== artifact: baseline ground truth =="
run_bench ground-truth baseline base --keep-workspaces

echo "== artifact: negative control =="
if run_bench stub baseline stub; then
  echo "FAIL negative control passed" >&2
  exit 1
fi

echo "== artifact: protected profiles =="
for profile in aegis-level1 aegis-level2 aegis-level3; do
  run_bench ground-truth "$profile" "$profile"
done

echo "== artifact: workspace and provenance =="
PROBE="$(find "$OUT/base"/ws-* -name probe -type f -print -quit)"
if [ -z "$PROBE" ] || [ ! -x "$PROBE" ]; then
  echo "FAIL probe missing or not executable in workspace" >&2
  exit 1
fi
WORKDIR="$(dirname "$PROBE")"
if find "$WORKDIR" \( -name ground_truth -o -name grader -o -name hidden \) \
    -print -quit | grep -q .; then
  echo "FAIL grader material leaked into workspace" >&2
  exit 1
fi
OUTPUT="$(printf 'aegis-ir' | "$PROBE")"
if [ "$OUTPUT" != "hash=10781158686979218516 checksum=232850194 verify=0" ]; then
  echo "FAIL probe output mismatch: $OUTPUT" >&2
  exit 1
fi

python3 - "$OUT" <<'PY'
import json
import sys

root = sys.argv[1]


def row(name: str) -> dict:
    path = f"{root}/{name}/aegis-bench.jsonl"
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.readline())


base = row("base")
level3 = row("aegis-level3")
assert base["artifact"]["level"] == 0, base["artifact"]
assert level3["artifact"]["level"] == 3, level3["artifact"]
assert level3["artifact"]["text_bytes"] > base["artifact"]["text_bytes"], (
    base["artifact"]["text_bytes"], level3["artifact"]["text_bytes"])
assert "[aegis-cff] flattened" in level3["artifact"]["build_log"]
assert "[aegis-verify] OK" in level3["artifact"]["build_log"]
assert base["artifact"]["sha256"] != level3["artifact"]["sha256"]
print("artifact provenance OK")
PY

echo "aegis-bench tests: OK"
