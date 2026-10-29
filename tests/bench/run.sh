#!/usr/bin/env bash
# Aegis-Bench harness tests (offline; deterministic adapters only).
#
# Usage: run.sh <path-to-aegis-bench-root>
# Requires python3 and a C++17 compiler on PATH (set BENCH_CXX to override).

set -eu
BENCH_ROOT="${1:?usage: run.sh <tools/aegis-bench>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

# Manifest hashes must match the committed files; a stale hash means someone
# edited a task without re-running `aegis-bench hash`.
(cd "$BENCH_ROOT" && python3 -m aegis_bench check \
  --tasks-root "$REPO_ROOT/benchmarks/tasks-public")

(cd "$BENCH_ROOT" && python3 -m unittest discover -s tests -v)
