"""Offline tests for campaigns, resume and report auditing."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
REPO_ROOT = TOOL_ROOT.parents[1]
TASKS_ROOT = REPO_ROOT / "benchmarks" / "tasks-public"
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.audit import audit_path  # noqa: E402
from aegis_bench.campaign import (  # noqa: E402
    ExperimentError, _CampaignLock, load_experiment, plan_cells, run_campaign)
from aegis_bench.runner import RunRecord  # noqa: E402
from aegis_bench.grader import Grade  # noqa: E402
from aegis_bench.landlock import abi_version  # noqa: E402


class _FakeRunner:
    """Exercise campaign semantics without compiling or grading C++."""

    def __init__(self, **_kwargs):
        self.environment = {
            "commit": "a" * 40,
            "commit_dirty": "no",
            "python": "3.12",
            "platform": "offline-test",
            "machine": "test",
        }

    def run(self, tasks, agents, *, profile, repetitions,
            repetition_start):
        records = []
        for task in tasks:
            for agent in agents:
                for offset in range(repetitions):
                    repetition = repetition_start + offset
                    records.append(RunRecord(
                        run_id=f"{task.id}-{profile}-{agent.name}-{repetition}",
                        task_id=task.id,
                        task_hash=task.content_hash,
                        agent=agent.name,
                        adversary=agent.adversary,
                        adapter_version=str(getattr(agent, "version", "")),
                        access="n/a",
                        calibration={},
                        profile=profile,
                        repetition=repetition,
                        started_utc="2026-11-12T00:00:00Z",
                        duration_seconds=0.01,
                        grade=Grade(False, "hidden", "offline test double"),
                        ledger={
                            "tokens": None,
                            "tool_calls": 0,
                            "ledger_source": "self-reported by adapter",
                        },
                        budgets={"enforcement": {}},
                        environment=self.environment,
                        artifact={},
                        oracle={},
                        metering={},
                        task_protocol=task.protocol_dict(),
                        isolation={"adapter": "in-process", "sandbox": False},
                    ))
        return records


def _manifest(
        tmp: str,
        *,
        tasks: list[str] | None = None,
        profiles: list[str] | None = None,
        repetitions: int = 1,
        access: str = "oracle",
        require_broker_tools: bool = False,
        adapter_isolation: str = "in-process",
        require_sandbox: bool = False,
        ) -> Path:
    raw = {
        "schema_version": 1,
        "name": "offline-campaign",
        "purpose": "harness-validation",
        "primary_metric": "pass_rate",
        "tasks_root": str(TASKS_ROOT),
        "tasks": tasks or ["rolling-token-v1"],
        "agents": [{
            "id": "stub",
            "adapter": "stub",
            "expected_version": "builtin-test-double-v1",
        }],
        "profiles": profiles or ["baseline"],
        "repetitions": repetitions,
        "access": access,
        "order": "interleaved",
        "seed": 17,
        "require_clean": False,
        "require_meter": False,
        "require_broker_tools": require_broker_tools,
        "adapter_isolation": adapter_isolation,
        "require_sandbox": require_sandbox,
    }
    path = Path(tmp) / "experiment.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


class CampaignPlanningTests(unittest.TestCase):
    def test_interleaving_contains_every_profile_once_per_repetition(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(
                tmp, profiles=["baseline", "aegis-level1"],
                repetitions=2))
            cells = plan_cells(experiment)
        self.assertEqual(len(cells), 4)
        for repetition in (0, 1):
            block = [cell for cell in cells if cell.repetition == repetition]
            self.assertEqual(
                {cell.profile for cell in block},
                {"baseline", "aegis-level1"})

    def test_oracle_comparison_of_binary_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(
                tmp, tasks=["rolling-token-v2"],
                profiles=["baseline", "aegis-level3"]))
            with self.assertRaises(ExperimentError):
                experiment.resolve_tasks()

    def test_unknown_manifest_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _manifest(tmp)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["repetitons"] = 3
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ExperimentError):
                load_experiment(path)


class CampaignResumeTests(unittest.TestCase):
    def test_campaign_writes_then_resumes_without_rerunning(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(tmp))
            out = Path(tmp) / "out"
            first = run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            self.assertTrue(first.complete)
            self.assertFalse(first.resumed)
            self.assertEqual(len(first.records), 1)
            first_started = json.loads(
                (out / "campaign-state.json").read_text(encoding="utf-8")
            )["started_utc"]

            second = run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            state = json.loads(
                (out / "campaign-state.json").read_text(encoding="utf-8"))
            rows = [
                json.loads(line) for line in
                (out / "aegis-bench.jsonl").read_text(
                    encoding="utf-8").splitlines()
            ]
            leftovers = list(out.glob(".*.tmp"))

        self.assertTrue(second.complete)
        self.assertTrue(second.resumed)
        self.assertEqual(len(second.records), 1)
        self.assertEqual(state["started_utc"], first_started)
        self.assertEqual(state["cells_completed"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["campaign"]["cell_key"],
                         "rolling-token-v1|baseline|stub|0")
        self.assertEqual(rows[0]["record_schema_version"], 3)
        self.assertEqual(leftovers, [])

    def test_changed_manifest_cannot_resume_same_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _manifest(tmp)
            experiment = load_experiment(path)
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["repetitions"] = 2
            path.write_text(json.dumps(raw), encoding="utf-8")
            changed = load_experiment(path)
            with self.assertRaises(ExperimentError):
                run_campaign(
                    changed, repo_root=REPO_ROOT, out_dir=out,
                    runner_factory=_FakeRunner)

    def test_concurrent_writer_to_same_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(tmp))
            out = Path(tmp) / "out"
            out.mkdir()
            with _CampaignLock(out / ".campaign.lock"):
                with self.assertRaises(ExperimentError):
                    run_campaign(
                        experiment, repo_root=REPO_ROOT, out_dir=out,
                        runner_factory=_FakeRunner)


class AuditTests(unittest.TestCase):
    def test_round_trip_and_clean_offline_campaign_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(tmp))
            out = Path(tmp) / "out"
            result = run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            raw = json.loads(
                (out / "aegis-bench.jsonl").read_text(
                    encoding="utf-8").splitlines()[0])
            loaded = RunRecord.from_dict(raw)
            report = audit_path(out, experiment=experiment)
        self.assertEqual(loaded.to_dict()["run_id"], raw["run_id"])
        self.assertEqual(loaded.task_protocol, raw["task_protocol"])
        self.assertEqual(loaded.campaign, raw["campaign"])
        self.assertTrue(report.ok(), report.issues)
        self.assertEqual(len(report.rows), len(result.records))

    def test_duplicate_and_missing_cells_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(tmp))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            path = out / "aegis-bench.jsonl"
            line = path.read_text(encoding="utf-8")
            path.write_text(line + line, encoding="utf-8")
            duplicate = audit_path(out, experiment=experiment)
            path.write_text("", encoding="utf-8")
            missing = audit_path(out, experiment=experiment)
        self.assertTrue(any(issue.code == "duplicate-cell"
                            for issue in duplicate.errors))
        self.assertTrue(any(issue.code in ("empty", "missing-cell")
                            for issue in missing.errors))

    def test_mixed_meter_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(
                tmp, profiles=["baseline", "aegis-level1"]))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            path = out / "aegis-bench.jsonl"
            rows = [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines()]
            for row in rows:
                row["ledger"]["tokens"] = 100
                row["ledger"]["ledger_source"] = "self-reported by adapter"
            rows[0]["metering"] = {
                "requests": 1,
                "requests_with_usage": 1,
                "total_tokens": 90,
            }
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8")
            report = audit_path(out, experiment=experiment)
        self.assertTrue(any(issue.code == "metering"
                            for issue in report.errors))

    def test_stale_task_protocol_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(tmp))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            path = out / "aegis-bench.jsonl"
            row = json.loads(path.read_text(encoding="utf-8"))
            row["task_protocol"]["experiment_use"] = "comparison"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            report = audit_path(out, experiment=experiment)
        self.assertTrue(any(issue.code == "stale-task-protocol"
                            for issue in report.errors))

    def test_audit_finds_nested_data_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(tmp))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            data = out / "data"
            data.mkdir()
            (out / "aegis-bench.jsonl").replace(data / "aegis-bench.jsonl")
            report = audit_path(out, experiment=experiment)
        self.assertEqual(report.path, data / "aegis-bench.jsonl")
        self.assertTrue(report.ok(), report.issues)

    def test_required_tool_broker_traffic_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(
                tmp, require_broker_tools=True))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            report = audit_path(out, experiment=experiment)
        self.assertTrue(any(issue.code == "tool-broker"
                            for issue in report.errors))

    def test_adapter_isolation_mismatch_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(
                tmp, adapter_isolation="process"))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            report = audit_path(out, experiment=experiment)
        self.assertTrue(any(issue.code == "isolation"
                            for issue in report.errors))

    def test_required_sandbox_is_audited(self):
        if os.name != "posix" or abi_version() <= 0:
            self.skipTest("Landlock unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            experiment = load_experiment(_manifest(
                tmp, adapter_isolation="process", require_sandbox=True))
            out = Path(tmp) / "out"
            run_campaign(
                experiment, repo_root=REPO_ROOT, out_dir=out,
                runner_factory=_FakeRunner)
            report = audit_path(out, experiment=experiment)
        self.assertTrue(any(issue.code == "sandbox"
                            for issue in report.errors))


if __name__ == "__main__":
    unittest.main()
