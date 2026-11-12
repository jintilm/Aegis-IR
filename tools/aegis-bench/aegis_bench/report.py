"""Report generation: JSONL (raw rows), CSV (spreadsheet) and Markdown.

Reports are derived from records only; nothing is recomputed differently here
from what the runner recorded, so a number in the Markdown summary always has
a raw row behind it.

Two kinds of number appear here, labelled differently on purpose:

* **measured** — pass/fail, case counts, wall clock, oracle queries (counted
  by the harness broker), and tokens when the run went through the harness
  metering proxy (the provider's own usage report);
* **self-reported** — tokens on runs without a meter, and tool calls, which
  come from the adapter and which the harness cannot corroborate.

A row can therefore carry a metered token total *and* the adapter's figure.
Where both exist the metered one is reported, and the disagreement between
them is in the row (`metering.reported_by_adapter`,
`metering.adapter_exceeds_metered`): an adapter that claims more than the
proxy saw had traffic leave the proxy, which is the one direction the meter
can catch.

Pass rates carry a Wilson 95% interval, which behaves correctly at 0/n and
n/n where the textbook normal interval collapses. A delta between groups gets
an interval only once both groups have at least two runs; with one run the
report says so instead of inventing a spread.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev, stdev
from typing import Any, Iterable

from .runner import RunRecord

CSV_FIELDS = [
    "record_schema", "campaign_id", "campaign_purpose",
    "task_schema", "experiment_use", "tool_network",
    "run_id", "task_id", "task_hash", "agent", "adapter_version", "access",
    "adversary",
    "profile",
    "repetition", "started_utc", "duration_seconds", "passed", "stage",
    "reason", "cases_total", "cases_passed", "success_rate",
    "tokens", "metered_tokens", "metered_requests", "tool_calls",
    "broker_tool_calls", "broker_tool_denied", "broker_tool_source",
    "adapter_isolation", "sandbox", "ledger_source",
    "artifact_sha256",
    "artifact_bytes", "artifact_text", "adapter_timeout", "oracle_queries",
    "oracle_refused", "oracle_budget", "task_calibration", "private", "commit",
    "commit_dirty",
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


def atomic_write_text(path: Path, text: str, *,
                      newline: str | None = None) -> None:
    """Replace a report atomically so a killed process cannot truncate it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_jsonl(records: Iterable[RunRecord], path: Path) -> None:
    text = "".join(json.dumps(record.to_dict(), sort_keys=True) + "\n"
                   for record in records)
    atomic_write_text(Path(path), text, newline="\n")


def write_csv(records: Iterable[RunRecord], path: Path) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for record in records:
        row = record.to_dict()
        campaign = row.get("campaign") or {}
        writer.writerow({
            "record_schema": row.get("record_schema_version", ""),
            "campaign_id": campaign.get("id", ""),
            "campaign_purpose": campaign.get("purpose", ""),
            "task_schema": (row.get("task_protocol") or {}).get(
                "schema_version", ""),
            "experiment_use": (row.get("task_protocol") or {}).get(
                "experiment_use", ""),
            "tool_network": ((row.get("task_protocol") or {}).get(
                "tool_policy") or {}).get("network", ""),
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
            "metered_tokens": _ledger_value(row.get("metering") or {},
                                            "total_tokens"),
            "metered_requests": _ledger_value(row.get("metering") or {},
                                              "requests"),
            "tool_calls": _ledger_value(row["ledger"], "tool_calls"),
            "broker_tool_calls": _ledger_value(
                row.get("tools") or {}, "requests"),
            "broker_tool_denied": _ledger_value(
                row.get("tools") or {}, "denied"),
            "broker_tool_source": (row.get("tools") or {}).get(
                "source", ""),
            "adapter_isolation": (row.get("isolation") or {}).get(
                "adapter", ""),
            "sandbox": (row.get("isolation") or {}).get(
                "sandbox", ""),
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
            "task_calibration": (row.get("calibration", {}) or {}).get(
                row.get("access", ""), {}).get("status", ""),
            "private": row.get("private", False),
            "commit": row["environment"].get("commit", ""),
            "commit_dirty": row["environment"].get("commit_dirty", ""),
        })
    atomic_write_text(Path(path), buffer.getvalue(), newline="")


def _metered(record: RunRecord) -> Any:
    """The provider-attested token total for this run, if there is one."""
    block = record.metering or {}
    value = block.get("total_tokens")
    return value if isinstance(value, (int, float)) else None


def _tokens(rows: list[RunRecord]) -> list[float]:
    """Token cost per run, preferring the metered figure over the self-report.

    Mixing the two within one column would make the column's provenance
    unreadable, so a list is built from metered values only when every run
    that has a cost has one; otherwise rows fall back to the adapter's number
    and the report says which rows those were.
    """
    metered = [r for r in rows if _metered(r) is not None]
    costed = [r for r in rows if isinstance(r.ledger.get("tokens"), (int, float))
              or _metered(r) is not None]
    if costed and len(metered) == len(costed):
        return [float(_metered(r)) for r in metered]
    return [r.ledger["tokens"] for r in rows
            if isinstance(r.ledger.get("tokens"), (int, float))]


def _oracle_queries(rows: list[RunRecord]) -> list[float]:
    return [r.oracle["queries"] for r in rows
            if r.oracle and isinstance(r.oracle.get("queries"), (int, float))]


def _token_kind(records: list[RunRecord]) -> str:
    """``metered`` / ``mixed`` / ``self-rep`` -- what the token column is."""
    costed = [r for r in records if _metered(r) is not None
              or isinstance(r.ledger.get("tokens"), (int, float))]
    metered = [r for r in costed if _metered(r) is not None]
    if not costed or not metered:
        return "self-rep"
    return "metered" if len(metered) == len(costed) else "mixed"


def _token_provenance(records: list[RunRecord]) -> str:
    """One sentence saying who produced the token column, and for which rows."""
    costed = [r for r in records if _metered(r) is not None
              or isinstance(r.ledger.get("tokens"), (int, float))]
    metered = [r for r in costed if _metered(r) is not None]
    if not costed:
        return ("Token and tool-call figures are **self-reported by the "
                "adapter**; the harness cannot corroborate them.")
    if len(metered) == len(costed):
        return ("Token figures are **measured**: each run went through a "
                "harness-owned metering proxy and the totals are the "
                "provider's own `usage` report. Tool-call figures remain "
                "self-reported by the adapter.")
    return (f"Token figures are **metered for {len(metered)} of "
            f"{len(costed)} costed runs** (provider `usage` via the harness "
            f"proxy) and **self-reported by the adapter** for the rest; the "
            f"row's `ledger_source` says which. Tool-call figures are "
            f"self-reported.")


def _tool_provenance(records: list[RunRecord]) -> str:
    observed = [record for record in records if record.tools]
    brokered = [record for record in observed
                if record.tools.get("requests", 0) > 0]
    if not observed:
        return ("Tool-call figures are **self-reported by the adapter**; no "
                "harness-owned tool broker block is present.")
    if len(brokered) == len(observed):
        return ("Tool calls are **measured by the harness-owned broker** for "
                "every costed run that used tools; workspace reads, probe "
                "executions, disassembly and submissions pass through its "
                "policy and budget checks.")
    return (f"Tool calls are **brokered for {len(brokered)} of "
            f"{len(observed)} runs with a broker block**. Rows with "
            f"`requests: 0` bypassed the broker and retain the adapter's "
            f"self-report; do not treat the two as equivalent.")


def write_markdown(records: Iterable[RunRecord], path: Path) -> None:
    records = list(records)
    lines: list[str] = ["# Aegis-Bench run report", ""]

    if not records:
        lines.append("_No runs recorded._")
        atomic_write_text(Path(path), "\n".join(lines) + "\n", newline="\n")
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
        _token_provenance(records),
        "",
        _tool_provenance(records),
        "",
        "Pass/fail, case counts, wall clock and oracle queries are always "
        "measured by the harness. Pass rates carry a Wilson 95% interval; "
        "cost deltas carry an interval only when both groups have at least "
        "two runs. A run row states which budgets were enforced.",
        "",
    ]
    versions = sorted({f"{r.agent} {r.adapter_version or '(no version)'}"
                       for r in records})
    lines += ["- Adapters: " + ", ".join(f"`{v}`" for v in versions), ""]
    campaigns = sorted({
        (r.campaign.get("id", ""), r.campaign.get("manifest_sha256", ""),
         r.campaign.get("purpose", ""))
        for r in records if r.campaign and r.campaign.get("id")
    })
    if campaigns:
        rendered = ", ".join(
            f"`{name}` ({purpose or 'purpose unset'}, manifest "
            f"`{digest[:12] or '?'}`)" for name, digest, purpose in campaigns)
        lines += ["- Campaigns: " + rendered, ""]
    isolation_modes = sorted({
        str((record.isolation or {}).get("adapter") or "legacy/unspecified")
        for record in records
    })
    sandboxed = sum(1 for record in records
                    if (record.isolation or {}).get("sandbox"))
    lines += [
        "- Adapter isolation: "
        + ", ".join(f"`{mode}`" for mode in isolation_modes)
        + f"; {sandboxed}/{len(records)} row(s) record a sandbox",
        "",
    ]
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
    calibration_rows: list[tuple[str, str, dict[str, Any]]] = []
    seen_calibration: set[tuple[str, str]] = set()
    for record in records:
        if not record.artifact:
            continue
        key = (record.task_id, record.access)
        if key in seen_calibration:
            continue
        seen_calibration.add(key)
        entry = (record.calibration or {}).get(record.access) or {}
        calibration_rows.append((record.task_id, record.access, entry))
    if calibration_rows:
        parts = []
        for task_id, access_mode, cal in calibration_rows:
            status = cal.get("status") or "uncalibrated"
            detail = ", ".join(str(x) for x in (
                cal.get("model", ""), cal.get("baseline_pass_rate", ""),
                f"N={cal.get('runs')}" if cal.get("runs") else "") if x != "")
            parts.append(f"`{task_id}` [{access_mode}] = {status}"
                         + (f" ({detail})" if detail else ""))
        lines += ["- Calibration: " + "; ".join(parts), ""]
        if any((cal.get("status") or "uncalibrated") != "comparison-ready"
               for _, _, cal in calibration_rows):
            lines += [
                "**Calibration.** At least one task is not `comparison-ready` "
                "for this agent and access mode. What that costs the reader "
                "depends on which number is being read: at the **floor** "
                "(baseline never succeeds) there is no headroom and neither a "
                "success nor a cost delta is interpretable; at the "
                "**ceiling** (baseline always succeeds) a *success-rate* delta "
                "is uninterpretable but a **cost** delta still is, because the "
                "success criterion is held fixed across both arms; with no "
                "record at all, treat both as descriptive. Recalibrate before "
                "citing anything here as an effect.",
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
        f"wall s (mean±sd) | tokens ({_token_kind(records)}) | "
        "oracle queries (mean) |",
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
        f"wall s (mean±sd) | tokens ({_token_kind(records)}) | "
        "oracle queries (total) |",
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
        kind = _token_kind(records)
        token_note = {
            "metered": "and the token delta come from the provider's own "
                       "usage report, captured by the harness metering proxy.",
            "mixed": "are measured, and so is the token delta for most rows; "
                     "the rows whose `ledger_source` says self-reported use "
                     "the adapter's own arithmetic instead.",
            "self-rep": "are measured; the token delta is self-reported by "
                        "the adapter and cannot be corroborated.",
        }[kind]
        lines += [
            "## Cost delta vs baseline",
            "",
            "Positive means the protected profile cost more. Wall-clock and "
            "oracle-query deltas " + token_note,
            "",
            "| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | "
            f"Δ tokens ({kind}) |",
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

    atomic_write_text(Path(path), "\n".join(lines) + "\n", newline="\n")


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
