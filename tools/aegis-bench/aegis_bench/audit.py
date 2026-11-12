"""Audit a JSONL run file before it is cited or resumed.

The audit is intentionally independent of report generation. A Markdown table
can be internally consistent while the JSONL underneath it contains duplicate
repetitions, mixed metering, a dirty commit, or a missing row. This module
checks those invariants directly against the raw rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .campaign import Experiment, ExperimentError, Cell, plan_cells
from .runner import RunRecord

_REQUIRED = (
    "run_id", "task_id", "task_hash", "agent", "profile", "repetition",
    "started_utc", "duration_seconds", "grade", "environment",
)


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    message: str
    run_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "run_id": self.run_id,
        }


@dataclass
class AuditReport:
    path: Path
    rows: list[RunRecord]
    issues: list[AuditIssue]

    @property
    def errors(self) -> list[AuditIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[AuditIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def ok(self, *, strict: bool = False) -> bool:
        return not self.errors and not (strict and self.warnings)

    def to_dict(self, *, strict: bool = False) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "rows": len(self.rows),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "ok": self.ok(strict=strict),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _resolve_jsonl(path: str | Path) -> Path:
    path = Path(path)
    if path.is_dir():
        direct = path / "aegis-bench.jsonl"
        nested = path / "data" / "aegis-bench.jsonl"
        path = direct if direct.is_file() or not nested.is_file() else nested
    return path


def _load_rows(path: Path) -> tuple[list[RunRecord], list[AuditIssue]]:
    rows: list[RunRecord] = []
    issues: list[AuditIssue] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return rows, [AuditIssue(
            "error", "file", f"cannot read {path}: {exc}")]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(AuditIssue(
                "error", "json", f"line {line_number}: invalid JSON: {exc}"))
            continue
        if not isinstance(raw, dict):
            issues.append(AuditIssue(
                "error", "shape",
                f"line {line_number}: row must be a JSON object"))
            continue
        missing = [key for key in _REQUIRED if key not in raw]
        if missing:
            issues.append(AuditIssue(
                "error", "shape",
                f"line {line_number}: missing field(s): {', '.join(missing)}",
                str(raw.get("run_id", ""))))
            continue
        try:
            record = RunRecord.from_dict(raw)
        except (TypeError, ValueError, KeyError) as exc:
            issues.append(AuditIssue(
                "error", "shape",
                f"line {line_number}: invalid run row: {exc}",
                str(raw.get("run_id", ""))))
            continue
        rows.append(record)
    return rows, issues


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _tokens(record: RunRecord) -> tuple[str, float] | None:
    metered = (record.metering or {}).get("total_tokens")
    if _numeric(metered):
        return "metered", float(metered)
    reported = (record.ledger or {}).get("tokens")
    if _numeric(reported):
        return "self-reported", float(reported)
    return None


def _is_infrastructure(record: RunRecord) -> bool:
    if record.grade.stage != "agent":
        return False
    text = f"{record.error} {record.grade.reason}".lower()
    return any(token in text for token in (
        "http ", "timed out", "timeout", "exceeded its", "upstream",
        "connection", "ssl", "cloudflare", "capacity"))


def _audit_campaign(
        rows: list[RunRecord],
        experiment: Experiment,
        issues: list[AuditIssue],
        *,
        allow_private: bool,
        ) -> None:
    expected: dict[str, Cell] = {
        cell.key: cell for cell in plan_cells(experiment)}
    seen: dict[str, RunRecord] = {}
    current_hashes: dict[str, str] = {}
    current_protocols: dict[str, dict[str, Any]] = {}
    binary_tasks: set[str] = set()
    try:
        for task in experiment.resolve_tasks(allow_private=allow_private):
            current_hashes[task.id] = task.content_hash
            current_protocols[task.id] = task.protocol_dict()
            if task.artifact is not None:
                binary_tasks.add(task.id)
    except ExperimentError as exc:
        issues.append(AuditIssue(
            "warning", "task-root",
            f"cannot verify current task hashes from this environment: {exc}"))
    for record in rows:
        if (record.task_protocol or {}).get("task_type") == "binary-recovery" \
                or record.artifact:
            binary_tasks.add(record.task_id)
    versions = {agent.id: agent.expected_version
                for agent in experiment.agents if agent.expected_version}

    for record in rows:
        campaign = record.campaign or {}
        if not campaign:
            issues.append(AuditIssue(
                "error", "campaign",
                f"row is not stamped with campaign {experiment.name!r}",
                record.run_id))
            continue
        if campaign.get("id") != experiment.name:
            issues.append(AuditIssue(
                "error", "campaign",
                f"campaign id {campaign.get('id')!r} does not match "
                f"{experiment.name!r}", record.run_id))
        if campaign.get("manifest_sha256") != experiment.manifest_sha256:
            issues.append(AuditIssue(
                "error", "campaign",
                "manifest hash does not match the audited experiment",
                record.run_id))
        if campaign.get("purpose") != experiment.purpose:
            issues.append(AuditIssue(
                "error", "campaign",
                f"campaign purpose {campaign.get('purpose')!r} does not match "
                f"{experiment.purpose!r}", record.run_id))
        if campaign.get("primary_metric") != experiment.primary_metric:
            issues.append(AuditIssue(
                "error", "campaign",
                f"primary metric {campaign.get('primary_metric')!r} does not "
                f"match {experiment.primary_metric!r}", record.run_id))
        if record.record_schema_version < 2:
            issues.append(AuditIssue(
                "error", "record-schema",
                "campaign rows require record_schema_version >= 2",
                record.run_id))
        key = campaign.get("cell_key")
        if not isinstance(key, str) or not key:
            issues.append(AuditIssue(
                "error", "campaign",
                "row has no campaign.cell_key", record.run_id))
            continue
        if key in seen:
            issues.append(AuditIssue(
                "error", "duplicate-cell",
                f"cell {key} appears more than once", record.run_id))
        seen[key] = record
        expected_cell = expected.get(key)
        if expected_cell is None:
            issues.append(AuditIssue(
                "error", "unexpected-cell",
                f"cell {key} is not in the experiment matrix", record.run_id))
            continue
        expected_access = (
            experiment.access if record.task_id in binary_tasks else "n/a")
        if record.access != expected_access:
            issues.append(AuditIssue(
                "error", "access",
                f"row access {record.access!r} does not match expected "
                f"{expected_access!r}", record.run_id))
        isolation = (record.isolation or {}).get("adapter")
        if isolation != experiment.adapter_isolation:
            issues.append(AuditIssue(
                "error", "isolation",
                f"row adapter isolation {isolation!r} does not match "
                f"{experiment.adapter_isolation!r}", record.run_id))
        if experiment.require_sandbox and not (
                record.isolation or {}).get("sandbox"):
            issues.append(AuditIssue(
                "error", "sandbox",
                "experiment requires a sandbox but this row ran without one",
                record.run_id))
        task_hash = current_hashes.get(record.task_id)
        if task_hash and record.task_hash != task_hash:
            issues.append(AuditIssue(
                "error", "stale-task",
                f"row task hash {record.task_hash!r} does not match the "
                f"current task {task_hash!r}", record.run_id))
        protocol = current_protocols.get(record.task_id)
        if protocol and record.task_protocol != protocol:
            issues.append(AuditIssue(
                "error", "stale-task-protocol",
                "row task_protocol does not match the current manifest "
                "metadata", record.run_id))
        expected_version = versions.get(record.agent)
        if expected_version and record.adapter_version != expected_version:
            issues.append(AuditIssue(
                "error", "adapter-version",
                f"adapter version {record.adapter_version!r} does not match "
                f"expected {expected_version!r}", record.run_id))
        broker = record.tools or {}
        if experiment.require_broker_tools and not broker.get("requests"):
            issues.append(AuditIssue(
                "error", "tool-broker",
                "experiment requires harness-broker tool traffic but this "
                "row has none", record.run_id))
        if broker.get("adapter_exceeds_broker"):
            issues.append(AuditIssue(
                "warning", "tool-broker",
                "adapter reported more tool calls than the harness broker "
                "observed; direct tool use may have bypassed the broker",
                record.run_id))
        if broker.get("denied"):
            issues.append(AuditIssue(
                "warning", "tool-broker",
                f"broker denied {broker['denied']} tool request(s)",
                record.run_id))

    for key in sorted(set(expected) - set(seen)):
        issues.append(AuditIssue(
            "error", "missing-cell", f"campaign cell was not completed: {key}"))
    if experiment.require_meter:
        for record in rows:
            if _tokens(record) and _tokens(record)[0] != "metered":
                issues.append(AuditIssue(
                    "error", "metering",
                    "experiment requires metered tokens but this row has only "
                    "an adapter self-report", record.run_id))
    if experiment.primary_metric == "tokens":
        for record in rows:
            if _tokens(record) is None:
                issues.append(AuditIssue(
                    "warning", "missing-cost",
                    "row has no token ledger although tokens is the primary "
                    "metric; it cannot enter a cost ratio", record.run_id))


def audit_path(
        path: str | Path,
        *,
        experiment: Experiment | None = None,
        allow_private: bool = False,
        ) -> AuditReport:
    """Load and audit one report's raw JSONL."""
    resolved = _resolve_jsonl(path)
    rows, issues = _load_rows(resolved)
    if not rows and not issues:
        issues.append(AuditIssue(
            "error", "empty", f"{resolved}: no run rows"))

    run_ids: set[str] = set()
    cells: dict[tuple[str, str, str, str, int], RunRecord] = {}
    commits: dict[str, list[RunRecord]] = {}
    dirty_rows: list[RunRecord] = []
    task_hashes: dict[str, str] = {}
    adapter_versions: dict[str, str] = {}
    repetitions: dict[
        tuple[str, str, str, str], list[int]] = {}
    token_kinds: dict[str, list[RunRecord]] = {
        "metered": [], "self-reported": []}

    for record in rows:
        if record.run_id in run_ids:
            issues.append(AuditIssue(
                "error", "duplicate-run",
                f"duplicate run_id {record.run_id!r}", record.run_id))
        run_ids.add(record.run_id)
        cell_key = (
            record.task_id, record.profile, record.agent, record.access,
            record.repetition)
        if cell_key in cells:
            issues.append(AuditIssue(
                "error", "duplicate-cell",
                f"duplicate cell {cell_key}", record.run_id))
        cells[cell_key] = record
        repetitions.setdefault(
            (record.task_id, record.profile, record.agent, record.access),
            []).append(record.repetition)

        commit = str((record.environment or {}).get("commit", ""))
        if not commit:
            issues.append(AuditIssue(
                "error", "commit",
                "row has no harness commit", record.run_id))
        else:
            commits.setdefault(commit, []).append(record)
        if (record.environment or {}).get("commit_dirty") != "no":
            dirty_rows.append(record)
        if not record.task_hash:
            issues.append(AuditIssue(
                "error", "task-hash",
                "row has no task content hash", record.run_id))
        else:
            previous = task_hashes.setdefault(record.task_id, record.task_hash)
            if previous != record.task_hash:
                issues.append(AuditIssue(
                    "error", "task-hash",
                    f"task {record.task_id} has multiple content hashes",
                    record.run_id))
        if not record.adapter_version:
            issues.append(AuditIssue(
                "warning", "adapter-version",
                "row has no adapter version", record.run_id))
        else:
            previous = adapter_versions.setdefault(
                record.agent, record.adapter_version)
            if previous != record.adapter_version:
                issues.append(AuditIssue(
                    "warning", "adapter-version",
                    f"agent {record.agent} has multiple adapter versions",
                    record.run_id))
        token = _tokens(record)
        if token:
            token_kinds[token[0]].append(record)
        tool_stats = record.tools or {}
        if tool_stats.get("adapter_exceeds_broker"):
            issues.append(AuditIssue(
                "warning", "tool-broker",
                "adapter reported more tool calls than the broker observed; "
                "direct tool use may have bypassed the broker",
                record.run_id))
        reported_tools = (record.ledger or {}).get("tool_calls")
        if (_numeric(reported_tools) and reported_tools > 0
                and not tool_stats.get("requests")):
            issues.append(AuditIssue(
                "warning", "tool-broker",
                "adapter reported tool calls but the broker saw no traffic",
                record.run_id))
        metering = record.metering or {}
        if metering:
            requests = metering.get("requests")
            with_usage = metering.get("requests_with_usage")
            if (isinstance(requests, int) and requests > 0
                    and isinstance(with_usage, int)
                    and with_usage < requests):
                issues.append(AuditIssue(
                    "warning", "metering",
                    f"provider usage covered {with_usage}/{requests} request(s)",
                    record.run_id))
            if metering.get("adapter_exceeds_metered"):
                issues.append(AuditIssue(
                    "warning", "metering",
                    "adapter reported more tokens than the proxy saw; traffic "
                    "may have bypassed the meter", record.run_id))
            if metering.get("client_disconnects"):
                issues.append(AuditIssue(
                    "warning", "metering",
                    f"{metering['client_disconnects']} abandoned call(s) carry "
                    f"no provider usage; the metered total is a floor",
                    record.run_id))
        artifact = record.artifact or {}
        if artifact:
            digest = str(artifact.get("sha256", ""))
            if len(digest) != 64 or any(ch not in "0123456789abcdef"
                                         for ch in digest.lower()):
                issues.append(AuditIssue(
                    "error", "artifact",
                    "artifact SHA-256 is missing or malformed", record.run_id))
        if record.access == "binary":
            if record.oracle and record.oracle.get("queries") is not None:
                issues.append(AuditIssue(
                    "error", "oracle",
                    "binary access must record oracle.queries as null",
                    record.run_id))
        elif record.access == "oracle" and artifact:
            queries = (record.oracle or {}).get("queries")
            if not isinstance(queries, int) or isinstance(queries, bool):
                issues.append(AuditIssue(
                    "error", "oracle",
                    "oracle access row has no harness-counted query total",
                    record.run_id))
        if record.error:
            issues.append(AuditIssue(
                "warning", "row-error",
                f"run recorded an error: {record.error.splitlines()[0]}",
                record.run_id))
        if _is_infrastructure(record):
            issues.append(AuditIssue(
                "warning", "infrastructure",
                "run failed in the adapter/relay layer; classify it as "
                "infrastructure, not an agent result", record.run_id))

    if len(commits) > 1:
        issues.append(AuditIssue(
            "error", "commit",
            f"rows came from {len(commits)} different commits: "
            f"{', '.join(sorted(commits))}"))
    if dirty_rows:
        issues.append(AuditIssue(
            "warning", "dirty-tree",
            f"{len(dirty_rows)} run(s) were recorded from a dirty worktree"))
    if token_kinds["metered"] and token_kinds["self-reported"]:
        issues.append(AuditIssue(
            "error", "metering",
            "file mixes metered and self-reported token rows; a single "
            "headline ratio would have unreadable provenance"))

    for cell, reps in sorted(repetitions.items()):
        unique = sorted(set(reps))
        if not unique:
            continue
        first, last = unique[0], unique[-1]
        missing = [rep for rep in range(first, last + 1)
                   if rep not in unique]
        if missing:
            issues.append(AuditIssue(
                "warning", "repetitions",
                f"cell {cell} is missing repetition(s): "
                f"{', '.join(str(rep) for rep in missing)}"))

    if experiment is not None:
        _audit_campaign(
            rows, experiment, issues, allow_private=allow_private)
    return AuditReport(path=resolved, rows=rows, issues=issues)
