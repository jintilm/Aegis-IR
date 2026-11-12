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

# rolling-token-v1 is the frozen reimplementation task; v2 is the
# binary-recovery task with artifact profiles. Both must keep working.
V1=rolling-token-v1
V2=rolling-token-v2

bench_run() { # <task> <agent> <profile> <out-name> [extra args...]
  local task="$1" agent="$2" profile="$3" name="$4"
  shift 4
  (cd "$BENCH_ROOT" && python3 -m aegis_bench run \
     --tasks-root "$TASKS_ROOT" --task "$task" \
     --adapter "$agent" --profile "$profile" \
     --plugin "$PLUGIN" --out "$OUT/$name" "$@")
}

echo "== reimplementation task (v1) still scores =="
bench_run "$V1" ground-truth baseline v1 >/dev/null

echo "== artifact: baseline ground truth (v2) =="
bench_run "$V2" ground-truth baseline base --keep-workspaces

echo "== artifact: negative control (v2) =="
if bench_run "$V2" stub baseline stub; then
  echo "FAIL negative control passed" >&2
  exit 1
fi

echo "== artifact: protected profiles (v2) =="
for profile in aegis-level1 aegis-level2 aegis-level3; do
  bench_run "$V2" ground-truth "$profile" "$profile"
done

echo "== artifact: workspace and provenance =="
PROBE="$(find "$OUT/base"/ws-* -name probe -type f -print -quit)"
if [ -z "$PROBE" ] || [ ! -x "$PROBE" ]; then
  echo "FAIL probe shim missing or not executable in workspace" >&2
  exit 1
fi
WORKDIR="$(dirname "$PROBE")"
if find "$WORKDIR" \( -name ground_truth -o -name grader -o -name hidden \) \
    -print -quit | grep -q .; then
  echo "FAIL grader material leaked into workspace" >&2
  exit 1
fi
# The workspace must contain the shim, not the probe binary: the second byte
# of an ELF is 'E', while a Python shebang starts with '#!'.
if [ "$(head -c 2 "$PROBE")" != "#!" ]; then
  echo "FAIL workspace 'probe' is not the oracle shim" >&2
  exit 1
fi

echo "== oracle accounting (v2) =="
# Three queries are counted at the broker even though the candidate is wrong.
bench_run "$V2" probe-query baseline oracle || true

echo "== binary access (v2) =="
# A protection comparison needs the artifact itself; under --access binary the
# workspace must hold the stripped ELF, not the shim.
bench_run "$V2" stub baseline binary --access binary --keep-workspaces \
  >/dev/null || true
BPROBE="$(find "$OUT/binary"/ws-* -name probe -type f -print -quit)"
if [ -z "$BPROBE" ] || \
   [ "$(head -c 4 "$BPROBE" | od -An -tx1 | tr -d ' \n')" != "7f454c46" ]; then
  echo "FAIL binary access did not place the ELF probe in the workspace" >&2
  exit 1
fi

echo "== campaign, resume and audit =="
CAMPAIGN_OUT="$OUT/campaign"
CAMPAIGN_CFG="$REPO_ROOT/experiments/offline-smoke.json"
(cd "$BENCH_ROOT" && python3 -m aegis_bench campaign \
  --config "$CAMPAIGN_CFG" --out "$CAMPAIGN_OUT")
(cd "$BENCH_ROOT" && python3 -m aegis_bench campaign \
  --config "$CAMPAIGN_CFG" --out "$CAMPAIGN_OUT")
(cd "$BENCH_ROOT" && python3 -m aegis_bench audit "$CAMPAIGN_OUT" \
  --experiment "$CAMPAIGN_CFG")

python3 - "$OUT" <<'PY'
import json
import sys

root = sys.argv[1]


def row(name: str) -> dict:
    path = f"{root}/{name}/aegis-bench.jsonl"
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.readline())


v1 = row("v1")
assert v1["task_id"] == "rolling-token-v1", v1["task_id"]
assert v1["artifact"] == {}, "a reimplementation task must not build a probe"
assert v1["oracle"] == {}, v1["oracle"]
assert v1["budgets"]["enforcement"]["oracle_queries"] == "n/a (no probe)"
assert v1["grade"]["passed"], v1["grade"]

base = row("base")
level3 = row("aegis-level3")
assert base["artifact"]["level"] == 0, base["artifact"]
assert level3["artifact"]["level"] == 3, level3["artifact"]
assert level3["artifact"]["text_bytes"] > base["artifact"]["text_bytes"], (
    base["artifact"]["text_bytes"], level3["artifact"]["text_bytes"])
assert "[aegis-cff] flattened" in level3["artifact"]["build_log"]
assert "[aegis-verify] OK" in level3["artifact"]["build_log"]
assert base["artifact"]["sha256"] != level3["artifact"]["sha256"]
# The ground-truth adapter never queries, so the broker must report zero.
assert base["oracle"]["queries"] == 0, base["oracle"]
assert base["budgets"]["enforcement"]["oracle_queries"] == (
    "counted by harness broker (no cap)")
# The probe-query adapter asks three times; the harness counted them.
queries = row("oracle")
assert queries["oracle"]["queries"] == 3, queries["oracle"]
assert queries["oracle"]["refused"] == 0, queries["oracle"]
assert queries["oracle"]["failed"] == 0, queries["oracle"]
campaign = row("campaign")
assert campaign["campaign"]["id"] == "offline-harness-smoke", campaign
assert campaign["campaign"]["cell_key"] == (
    "rolling-token-v1|baseline|ground-truth-replay|0"), campaign
assert campaign["record_schema_version"] == 3, campaign
assert campaign["tools"]["requests"] >= 3, campaign["tools"]
assert campaign["tools"]["source"] == "harness tool broker", campaign["tools"]
with open(f"{root}/campaign/campaign-state.json", encoding="utf-8") as fh:
    state = json.load(fh)
assert state["complete"] is True, state
assert state["cells_completed"] == 1, state
# No host or user name may reach a committed report.
assert "host" not in base["environment"] and "user" not in base["environment"]
assert base["environment"]["machine"]
assert base["budgets"]["enforcement"]["adapter_timeout"] != "unset"
print("artifact provenance and oracle accounting OK")
PY

echo "aegis-bench tests: OK"
