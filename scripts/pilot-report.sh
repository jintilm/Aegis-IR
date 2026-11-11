#!/usr/bin/env bash
# Reproduce a real-model pilot report.
#
# Unlike release-report.sh this needs an out-of-tree adapter directory and an
# API key, so it is never part of CI. It refuses to run on a dirty tree and
# writes the machine-generated rows plus a README that states exactly what the
# numbers do and do not show.
#
# Usage:
#   ADAPTERS_DIR=/path/to/adapters LLM_API_KEY=... \
#     scripts/pilot-report.sh pilot-2026-11-11
#
# Optional: TASKS (comma-separated), PROFILES, REPS, STEPS, ACCESS
# (oracle|binary; use binary for anything that compares protection levels),
# and LLM_* variables.
set -euo pipefail

NAME="${1:-pilot}"
TASKS="${TASKS:-packed-record-v1}"
PROFILES="${PROFILES:-baseline,aegis-level3}"
REPS="${REPS:-3}"
STEPS="${STEPS:-30}"
ACCESS="${ACCESS:-oracle}"
ADAPTERS_DIR="${ADAPTERS_DIR:?set ADAPTERS_DIR to the out-of-tree adapter directory}"
IMAGE="${AEGIS_IMAGE:-aegis-ir-dev}"

# A fresh run needs a key; regenerating from REUSE_DATA must not. Check it only
# on the path that spends model budget.
if [ -z "${REUSE_DATA:-}" ]; then
  : "${LLM_API_KEY:?set LLM_API_KEY (never written to disk)}"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/docs/reports/$NAME"
DATA="$OUT/data"

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "error: working tree is dirty; commit before generating a report" >&2
  exit 2
fi
COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"

mkdir -p "$OUT"
rm -rf "$DATA"

if [ -n "${REUSE_DATA:-}" ]; then
  # Regenerate the report from a run produced by this same script/command
  # without spending the model budget again. The run.log is not recreated.
  echo "reusing existing run data from $REUSE_DATA" >&2
  cp -r "$REUSE_DATA" "$DATA"
  # The console log from the run that produced this data is evidence. A
  # regeneration succeeds it rather than truncating it.
  [ -s "$OUT/run.log" ] || : > "$OUT/run.log"
else
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$REPO_ROOT:/src" \
    -v "$ADAPTERS_DIR:/adapters" \
    -w /src/tools/aegis-bench \
    -e LLM_API_KEY \
    -e LLM_BASE_URL="${LLM_BASE_URL:-https://jpn.cdn.moxuna.com/v1}" \
    -e LLM_MODEL="${LLM_MODEL:-deepseek-v4.1-flash}" \
    -e PYTHONPATH=/adapters \
    -e LLM_STEPS="$STEPS" \
    -e LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-16384}" \
    -e LLM_REASONING_LIMIT="${LLM_REASONING_LIMIT:-12000}" \
    -e LLM_SAVE_DIR=/tmp/submissions \
    -e BENCH_ACCESS="$ACCESS" \
    "$IMAGE" bash -c \
    "python3 /adapters/run_pilot.py '$TASKS' '$REPS' '/src/docs/reports/$NAME/data' '$PROFILES'" \
    2>&1 | tee "$OUT/run.log"
fi

python3 - "$DATA/aegis-bench.jsonl" "$OUT/README.md" "$NAME" "$COMMIT" \
  "$TASKS" "$PROFILES" "$REPS" "$STEPS" "$ACCESS" "$REPO_ROOT" <<'PY'
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

(jsonl, readme, name, commit, tasks, profiles, reps, steps, access,
 repo_root) = sys.argv[1:11]
rows = [json.loads(line) for line in Path(jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]

model = rows[0]["ledger"].get("model", "?") if rows else "?"
endpoint = rows[0]["ledger"].get("endpoint", "?") if rows else "?"
ledger0 = rows[0].get("ledger", {}) if rows else {}
versions = sorted({r.get("adapter_version", "") for r in rows})
env = rows[0].get("environment", {}) if rows else {}
# The run stamped its own commit; the generator may be newer. Report the
# commit the data came from, not the one the script happens to be at.
commit = env.get("commit") or commit
dirty = env.get("commit_dirty", "?")
recorded_access = sorted({r["access"] for r in rows if r.get("access")})
if recorded_access:
    access = ", ".join(recorded_access)
else:
    # Rows written before access modes existed ran with the shim in the
    # workspace; that is oracle access, whatever the flag would say today.
    access = "oracle (predates access modes; workspace held the shim)"

groups = defaultdict(list)
for row in rows:
    groups[row["profile"]].append(row)


def declared_calibration(task_id: str, mode: str) -> dict:
    """Read the task manifest's calibration for this access mode.

    The manifest is the current statement of record; the rows carry the
    snapshot that was in force at run time. Both are kept, and a reader can
    see when they disagree.
    """
    path = (Path(repo_root) / "benchmarks" / "tasks-public" / task_id
            / "task.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cal = raw.get("calibration") or {}
    if "status" in cal:  # manifests written before the per-mode split
        return cal if cal.get("access", mode) == mode else {}
    return cal.get(mode) or {}


mode = access.split(" ")[0]
cal_lines: list[str] = []
cal_status: list[tuple[str, str]] = []
for task_id in (t for t in tasks.split(",") if t):
    cal = declared_calibration(task_id, mode)
    if not cal:
        cal_lines.append(f"- task calibration: `{task_id}` has no record for "
                         f"`{mode}` access")
        cal_status.append((task_id, "uncalibrated"))
        continue
    status = cal.get("status", "uncalibrated")
    rate = cal.get("baseline_pass_rate")
    rate_text = f"{float(rate):.0%}" if isinstance(rate, (int, float)) else "n/a"
    cal_lines.append(
        f"- task calibration: `{task_id}` under `{mode}` access is "
        f"**{status}** — baseline {rate_text} over N={cal.get('runs', '?')} "
        f"(`{cal.get('model', '?')}`, {cal.get('date', '?')})")
    cal_status.append((task_id, status))

floor_tasks = [t for t, s in cal_status if s != "ceiling"
               and s != "comparison-ready"]
ceiling_tasks = [t for t, s in cal_status if s == "ceiling"]

lines = [
    f"# Pilot report: {name}", "",
    f"Generated by `scripts/pilot-report.sh` from commit `{commit}` "
    f"(dirty: {dirty}).", "",
    "**This is a pilot, not a claim.** It uses a small N, one task family and "
    "one model, and it is not cited from the claims ledger.", "",
    "## Configuration", "",
    f"- model: `{model}`",
    f"- endpoint: `{endpoint}` (shared relay)",
    f"- adapter source hash: {', '.join('`' + v + '`' for v in versions) or 'n/a'}",
    f"- tasks: `{tasks}`",
    f"- profiles: `{profiles}`",
    f"- repetitions per cell: {reps}",
    f"- step budget: {steps}",
    f"- access: {access}",
    *cal_lines,
    "- adapter policy: streaming SSE, thinking enabled, reasoning watchdog, "
    "fresh conversation after repeated unproductive replies, repeated "
    "submit prompt in the wrap phase "
    "(see `docs/reference-adapter.md`)",
    f"- reasoning watchdog: {ledger0.get('reasoning_limit_chars', 'n/a')} "
    f"chars; restart after {ledger0.get('restart_after', 'n/a')} unproductive "
    f"replies; conversation cap recorded per row",
    "",
    "## Results", "",
    "| profile | runs | submitted | passed | passed/runs | oracle queries "
    "(mean) | wall s (mean) | tokens (mean) |",
    "|---|---|---|---|---|---|---|---|",
]

for profile in sorted(groups):
    group = groups[profile]
    submitted = sum(1 for r in group if r["ledger"].get("stop_reason") == "submitted")
    passed = sum(1 for r in group if r["grade"]["passed"])
    oracle = [r["oracle"]["queries"] for r in group
              if r.get("oracle")
              and isinstance(r["oracle"].get("queries"), (int, float))]
    wall = [r["duration_seconds"] for r in group]
    tokens = [r["ledger"]["tokens"] for r in group
              if isinstance(r["ledger"].get("tokens"), (int, float))]
    oracle_cell = (f"{statistics.mean(oracle):.1f}" if oracle else
                   ("not counted (binary access)" if mode == "binary"
                    else "n/a"))
    tokens_cell = f"{statistics.mean(tokens):.0f}" if tokens else "n/a"
    lines.append(
        f"| {profile} | {len(group)} | {submitted} | {passed} | "
        f"{passed}/{len(group)} | {oracle_cell} | "
        f"{statistics.mean(wall):.1f} | {tokens_cell} |")

lines += [
    "",
    "Rows with `agent` as the failure stage are attempts that produced no "
    "submission within the step budget; they carry oracle counts but no token "
    "ledger. They are reported, not dropped.",
    "",
    "## What this shows", "",
    "- whether a real model can produce a graded submission on a deliberately "
    "non-standard task, and at what measured cost (oracle queries, wall clock) "
    "and self-reported cost (tokens, tool calls);",
    "- whether the protected profile changes either, with the variance the "
    "repetitions actually exhibit;",
    "- the probe's artifact size difference between the two profiles.",
    "",
    "## What this does **not** show", "",
    *(["- **No protection effect is measurable in this run at all.** The "
       "agent's workspace held an oracle shim whose behaviour is identical in "
       "every artifact profile; it could not inspect the artifact, so levels "
       "1–3 presented exactly the same information as the baseline. A "
       "level-vs-baseline difference here is noise, not evidence. Protection "
       "comparisons need `--access binary`.", ""]
      if access.startswith("oracle") else []),
    *([f"- **`{', '.join(floor_tasks)}` is not calibrated to a measurable "
       "baseline** for this agent and access mode: the baseline never passed "
       "there, or there is no record. Neither a success-rate nor a cost delta "
       "is interpretable on such a task — the agent fails for reasons that "
       "have nothing to do with the protection.", ""]
      if floor_tasks else []),
    *([f"- **`{', '.join(ceiling_tasks)}` is at the ceiling** for this agent "
       "and access mode: the unprotected baseline already passes every run. A "
       "*success-rate* delta is therefore saturated and meaningless, but a "
       "**cost** delta is still interpretable, because both arms are held to "
       "the same success criterion. Read the token/wall figures, not the pass "
       "column, and do not describe the result as protection changing "
       "success.", ""]
      if ceiling_tasks else []),
    "- **No effectiveness claim.** N is small, only one task and one model were "
    "run, and the model sits at or near the floor on this task; a 0% vs 0% "
    "comparison cannot demonstrate a protection effect.",
    "- No claim about other attacker classes or larger models.",
    "- Token figures include an estimate for calls aborted by the reasoning "
    "watchdog (`tokens_source` and `aborted_tokens_estimate` in the JSONL mark "
    "the share).",
    "- Model and relay drift: rerunning later may produce different costs for "
    "the same model id.",
    "",
    "## Files", "",
    "- `data/aegis-bench.jsonl` — one row per run, including provenance;",
    "- `data/aegis-bench.csv` — spreadsheet view;",
    "- `data/aegis-bench.md` — harness-generated report with Wilson intervals "
    "and the baseline cost delta;",
    "- `run.log` — adapter/runner console output (contains no credentials).",
    "",
]
Path(readme).write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {readme}")
PY

echo "pilot report written to $OUT"
