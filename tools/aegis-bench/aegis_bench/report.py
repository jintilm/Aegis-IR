"""Report generation: JSONL (raw rows), CSV (spreadsheet) and Markdown.

Reports are derived from records only; nothing is recomputed differently here
from what the runner recorded, so a number in the Markdown summary always has
a raw row behind it.

Cost fields that the harness cannot observe independently (token counts, tool
calls) are marked as self-reported. Putting the caveat in the report itself
keeps it attached to the number wherever the report travels.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from .runner import RunRecord

CSV_FIELDS = [
    "run_id", "task_id", "task_hash", "agent", "adversary", "profile",
    "repetition", "started_utc", "duration_seconds", "passed", "stage",
    "reason", "cases_total", "cases_passed", "success_rate",
    "tokens", "tool_calls", "ledger_source", "artifact_sha256",
    "artifact_bytes", "artifact_text", "adapter_timeout", "private", "commit",
    "commit_dirty",
]


def _ledger_value(ledger: dict[str, Any], key: str) -> Any:
    value = ledger.get(key, "")
    return value


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
                "private": row.get("private", False),
                "commit": row["environment"].get("commit", ""),
                "commit_dirty": row["environment"].get("commit_dirty", ""),
            })


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
        "Token, tool-call, oracle-query and cost figures are **self-reported "
        "by the adapter**; the harness cannot observe them independently. "
        "Pass/fail and case counts are measured. A run row states which "
        "budgets were actually enforced.",
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
            "Binary-recovery runs place only a stripped probe in the agent "
            "workspace. Each row records the probe's SHA-256 and size; the "
            "probe's build log is in the JSONL row. Oracle queries are made "
            "by the adapter and are not observable by the harness.",
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
        "| profile | agent | task | runs | pass | success rate | "
        "wall s (mean±sd) | tokens (mean) | tool calls (mean) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (profile, agent, task_id), rows in sorted(groups.items()):
        passes = sum(1 for r in rows if r.grade.passed)
        rates = [r.grade.success_rate for r in rows]
        durations = [r.duration_seconds for r in rows]
        tokens = [r.ledger["tokens"] for r in rows
                  if isinstance(r.ledger.get("tokens"), (int, float))]
        calls = [r.ledger["tool_calls"] for r in rows
                 if isinstance(r.ledger.get("tool_calls"), (int, float))]
        lines.append(
            f"| {profile} | {agent} | {task_id} | {len(rows)} | "
            f"{passes}/{len(rows)} | {mean(rates):.0%} | "
            f"{mean(durations):.2f}±{pstdev(durations):.2f} | "
            f"{(f'{mean(tokens):.0f}' if tokens else 'n/a')} | "
            f"{(f'{mean(calls):.1f}' if calls else 'n/a')} |")

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
