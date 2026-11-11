"""Report generation: JSONL (raw rows), CSV (spreadsheet) and Markdown.

Reports are derived from records only; nothing is recomputed differently here
from what the runner recorded, so a number in the Markdown summary always has
a raw row behind it.

Two kinds of number appear here, labelled differently on purpose:

* **measured** — pass/fail, case counts, wall clock, and oracle queries
  (counted by the harness broker);
* **self-reported** — tokens and tool calls, which come from the adapter and
  which the harness cannot corroborate.

Pass rates carry a Wilson 95% interval, which behaves correctly at 0/n and
n/n where the textbook normal interval collapses. A delta between groups gets
an interval only once both groups have at least two runs; with one run the
report says so instead of inventing a spread.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev, stdev
from typing import Any, Iterable

from .runner import RunRecord

CSV_FIELDS = [
    "run_id", "task_id", "task_hash", "agent", "adapter_version", "access",
    "adversary",
    "profile",
    "repetition", "started_utc", "duration_seconds", "passed", "stage",
    "reason", "cases_total", "cases_passed", "success_rate",
    "tokens", "tool_calls", "ledger_source", "artifact_sha256",
    "artifact_bytes", "artifact_text", "adapter_timeout", "oracle_queries",
    "oracle_refused", "oracle_budget", "private", "commit", "commit_dirty",
]

Z95 = 1.96


def wilson_interval(successes: int, total: int,
                    z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion.

    The normal approximation reports a zero-width interval at 0/n and n/n,
    which is exactly where a small benchmark spends most of its rows.
    """
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
              / denominator)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def mean_interval(values: list[float],
                  z: float = Z95) -> tuple[float, float] | None:
    """Mean ± z·SE for a small sample; ``None`` below two observations."""
    if len(values) < 2:
        return None
    centre = mean(values)
    half = z * stdev(values) / math.sqrt(len(values))
    return centre - half, centre + half


def _rate_cell(successes: int, total: int) -> str:
    interval = wilson_interval(successes, total)
    if interval is None:
        return "n/a"
    low, high = interval
    return f"{successes / total:.0%} [{low:.0%}-{high:.0%}]"


def _delta_cell(base: list[float], other: list[float], *,
                unit: str = "", digits: int = 2) -> str:
    """Difference of means, with an interval only when both sides have n>=2."""
    if not base or not other:
        return "n/a"
    delta = mean(other) - mean(base)
    if len(base) >= 2 and len(other) >= 2:
        se = math.sqrt(stdev(base) ** 2 / len(base)
                       + stdev(other) ** 2 / len(other))
        half = Z95 * se
        return (f"{delta:+.{digits}f} [{delta - half:+.{digits}f}, "
                f"{delta + half:+.{digits}f}]{unit}")
    return f"{delta:+.{digits}f}{unit} (n<2)"


def _ledger_value(ledger: dict[str, Any], key: str) -> Any:
    value = ledger.get(key, "")
    return value


def _oracle_value(record: RunRecord, key: str) -> Any:
    return record.oracle.get(key, "") if record.oracle else ""


def write_jsonl(records: Iterable[RunRecord], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")


def write_csv(records: Iterable[RunRecord], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            row = record.to_dict()
            writer.writerow({
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "task_hash": row["task_hash"],
                "agent": row["agent"],
                "adapter_version": row.get("adapter_version", ""),
                "access": row.get("access", ""),
                "adversary": row["adversary"],
                "profile": row["profile"],
                "repetition": row["repetition"],
                "started_utc": row["started_utc"],
                "duration_seconds": row["duration_seconds"],
                "passed": row["grade"]["passed"],
                "stage": row["grade"]["stage"],
                "reason": row["grade"]["reason"],
                "cases_total": row["grade"]["cases_total"],
                "cases_passed": row["grade"]["cases_passed"],
                "success_rate": row["grade"]["success_rate"],
                "tokens": _ledger_value(row["ledger"], "tokens"),
                "tool_calls": _ledger_value(row["ledger"], "tool_calls"),
                "ledger_source": row["ledger"].get("ledger_source", ""),
                "artifact_sha256": row.get("artifact", {}).get("sha256", ""),
                "artifact_bytes": row.get("artifact", {}).get("size_bytes", ""),
                "artifact_text": row.get("artifact", {}).get("text_bytes", ""),
                "adapter_timeout": row.get("budgets", {}).get(
                    "enforcement", {}).get("adapter_timeout", ""),
                "oracle_queries": row.get("oracle", {}).get("queries", ""),
                "oracle_refused": row.get("oracle", {}).get("refused", ""),
                "oracle_budget": row.get("budgets", {}).get(
                    "oracle_queries", ""),
                "private": row.get("private", False),
                "commit": row["environment"].get("commit", ""),
                "commit_dirty": row["environment"].get("commit_dirty", ""),
            })


def _tokens(rows: list[RunRecord]) -> list[float]:
    return [r.ledger["tokens"] for r in rows
            if isinstance(r.ledger.get("tokens"), (int, float))]


def _oracle_queries(rows: list[RunRecord]) -> list[float]:
    return [r.oracle["queries"] for r in rows
            if r.oracle and isinstance(r.oracle.get("queries"), (int, float))]


def write_markdown(records: Iterable[RunRecord], path: Path) -> None:
    records = list(records)
    lines: list[str] = ["# Aegis-Bench run report", ""]

    if not records:
        lines.append("_No runs recorded._")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    env = records[0].environment
    lines += [
        f"- Commit: `{env.get('commit') or 'unknown'}` "
        f"(dirty: {env.get('commit_dirty', '?')})",
        f"- Platform: {env.get('platform', '?')}",
        f"- Python: {env.get('python', '?')}",
        f"- Machine: `{env.get('machine', 'unknown')}` (salted hash; no host "
        f"or user name is recorded)",
        f"- Runs: {len(records)}",
        "",
        "Pass/fail, case counts, wall clock and oracle queries are measured by "
        "the harness. Token and tool-call figures are **self-reported by the "
        "adapter** and cannot be corroborated. Pass rates carry a Wilson 95% "
        "interval; cost deltas carry an interval only when both groups have at "
        "least two runs. A run row states which budgets were enforced.",
        "",
    ]
    versions = sorted({f"{r.agent} {r.adapter_version or '(no version)'}"
                       for r in records})
    lines += ["- Adapters: " + ", ".join(f"`{v}`" for v in versions), ""]
    # Rows written before access modes existed put the shim in the workspace,
    # i.e. oracle access; label them with the fact, not with "?".
    accesses = sorted({r.access or ("oracle" if r.artifact else "n/a")
                       for r in records})
    lines += ["- Access: " + ", ".join(f"`{a}`" for a in accesses), ""]
    if "oracle" in accesses:
        lines += [
            "**Under `oracle` access a protection comparison is structurally "
            "zero.** The agent gets a shim whose observable behaviour is "
            "identical in every profile; it cannot inspect the artifact, so a "
            "transform has nothing to act on. Any level-vs-baseline difference "
            "in those rows is noise, and no effectiveness claim may cite them. "
            "Protection cost can only be measured under `binary` access.",
            "",
        ]
    if any(record.private for record in records):
        lines += [
            "**PRIVATE TASK RESULTS — DO NOT PUBLISH.** At least one run used "
            "a task marked `private`. These rows live outside the public task "
            "set; publish them only through the custody process in "
            "`benchmarks/tasks-private/README.md`.",
            "",
        ]
    if any(record.artifact for record in records):
        lines += [
            "A binary-recovery row records an **access mode**. Under `oracle` "
            "the workspace holds only a shim and the probe stays with the "
            "harness broker, which counts every query and enforces "
            "`budgets.oracle_queries` when the manifest sets one. Under "
            "`binary` the workspace holds the stripped probe itself, so the "
            "agent can execute and disassemble it; queries are then "
            "**not counted** (the JSONL says `null`, not `0`). Neither mode is "
            "a sandbox: an adapter that reaches the artifact cache directly is "
            "not counted either way, and real runs need process isolation. "
            "Each row records the probe's SHA-256 and size; its build log is "
            "in the JSONL row.",
            "",
        ]
        artifacts: dict[str, dict[str, Any]] = {}
        for record in records:
            if record.artifact and record.profile not in artifacts:
                artifacts[record.profile] = record.artifact
        lines += [
            "| profile | artifact level | artifact `.text` | sha256 (12) |",
            "|---|---|---|---|",
        ]
        for profile, artifact in sorted(artifacts.items()):
            lines.append(
                f"| {profile} | {artifact.get('level', '?')} | "
                f"{artifact.get('text_bytes', '?')} | "
                f"`{str(artifact.get('sha256', ''))[:12]}` |")
        lines.append("")

    groups: dict[tuple[str, str, str], list[RunRecord]] = defaultdict(list)
    for record in records:
        groups[(record.profile, record.agent, record.task_id)].append(record)

    lines += [
        "## By (profile, agent, task)",
        "",
        "| profile | agent | task | runs | pass | pass rate (95% CI) | "
        "wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (profile, agent, task_id), rows in sorted(groups.items()):
        passes = sum(1 for r in rows if r.grade.passed)
        durations = [r.duration_seconds for r in rows]
        tokens = _tokens(rows)
        queries = _oracle_queries(rows)
        lines.append(
            f"| {profile} | {agent} | {task_id} | {len(rows)} | "
            f"{passes}/{len(rows)} | {_rate_cell(passes, len(rows))} | "
            f"{mean(durations):.2f}±{pstdev(durations):.2f} | "
            f"{(f'{mean(tokens):.0f}' if tokens else 'n/a')} | "
            f"{(f'{mean(queries):.1f}' if queries else 'n/a')} |")
    lines.append("")

    # Aggregate per (agent, profile) across tasks: the cell a protection
    # comparison actually asks about.
    aggregates: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for record in records:
        aggregates[(record.agent, record.profile)].append(record)
    lines += [
        "## By (agent, profile), across tasks",
        "",
        "| agent | profile | tasks | runs | pass | pass rate (95% CI) | "
        "wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (agent, profile), rows in sorted(aggregates.items()):
        passes = sum(1 for r in rows if r.grade.passed)
        durations = [r.duration_seconds for r in rows]
        tokens = _tokens(rows)
        queries = _oracle_queries(rows)
        tasks = len({r.task_id for r in rows})
        lines.append(
            f"| {agent} | {profile} | {tasks} | {len(rows)} | "
            f"{passes}/{len(rows)} | {_rate_cell(passes, len(rows))} | "
            f"{mean(durations):.2f}±{pstdev(durations):.2f} | "
            f"{(f'{mean(tokens):.0f}' if tokens else 'n/a')} | "
            f"{(f'{sum(queries):.0f}' if queries else 'n/a')} |")
    lines.append("")

    # Cost delta against the `baseline` profile, same agent and task.
    by_cell: dict[tuple[str, str], dict[str, list[RunRecord]]] = defaultdict(
        lambda: defaultdict(list))
    for record in records:
        by_cell[(record.agent, record.task_id)][record.profile].append(record)
    delta_rows: list[str] = []
    for (agent, task_id), profiles in sorted(by_cell.items()):
        base = profiles.get("baseline")
        if not base or len(profiles) < 2:
            continue
        base_wall = [r.duration_seconds for r in base]
        base_tokens = _tokens(base)
        base_queries = _oracle_queries(base)
        for profile, rows in sorted(profiles.items()):
            if profile == "baseline":
                continue
            wall = [r.duration_seconds for r in rows]
            tokens = _tokens(rows)
            queries = _oracle_queries(rows)
            delta_rows.append(
                f"| {agent} | {task_id} | baseline → {profile} | "
                f"{_delta_cell(base_wall, wall, unit=' s')} | "
                f"{_delta_cell(base_queries, queries, digits=1)} | "
                f"{_delta_cell(base_tokens, tokens, digits=0)} |")
    if delta_rows:
        lines += [
            "## Cost delta vs baseline",
            "",
            "Positive means the protected profile cost more. Wall-clock and "
            "oracle-query deltas are measured; the token delta is "
            "self-reported.",
            "",
            "| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | "
            "Δ tokens (self-rep) |",
            "|---|---|---|---|---|---|",
            *delta_rows,
            "",
        ]

    failures = [r for r in records if not r.grade.passed]
    if failures:
        lines += ["", "## Failures", "",
                  "| agent | task | stage | reason |", "|---|---|---|---|"]
        for record in failures:
            lines.append(f"| {record.agent} | {record.task_id} | "
                         f"{record.grade.stage} | {record.grade.reason} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(records: list[RunRecord], out_dir: Path,
                  stem: str = "aegis-bench") -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "jsonl": out_dir / f"{stem}.jsonl",
        "csv": out_dir / f"{stem}.csv",
        "markdown": out_dir / f"{stem}.md",
    }
    write_jsonl(records, paths["jsonl"])
    write_csv(records, paths["csv"])
    write_markdown(records, paths["markdown"])
    return paths
