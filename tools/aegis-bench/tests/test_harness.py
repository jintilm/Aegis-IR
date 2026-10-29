"""Harness tests for Aegis-Bench.

These run entirely offline with deterministic adapters: no model, no network,
no API keys. They exist to prove the harness measures what it claims:

- the ground truth scores 100% (the grader is not rigged to fail);
- a wrong-but-compiling candidate scores 0% (the grader is not trivially
  passable);
- an adapter failure is recorded as a failed run, not a crash;
- a task whose content changed after hashing is rejected;
- hidden files never appear in the agent workspace;
- reports carry the provenance fields the protocol requires.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.adapters.fake import BrokenAgent, ReplayAgent, StubAgent  # noqa: E402
from aegis_bench.grader import Grader  # noqa: E402
from aegis_bench.report import write_reports  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import TaskError, load_task  # noqa: E402

REPO_ROOT = TOOL_ROOT.parents[1]
TASKS_ROOT = REPO_ROOT / "benchmarks" / "tasks-public"
TASK_DIR = TASKS_ROOT / "rolling-token-v1"


def _ground_truth_source(task) -> dict[str, str]:
    return {"target.cpp": task.path(task.ground_truth).read_text(encoding="utf-8")}


class GraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(TASK_DIR)

    def test_ground_truth_passes(self):
        with Grader(self.task) as grader:
            grade = grader.grade(_ground_truth_source(self.task))
        self.assertTrue(grade.passed, grade.reason)
        self.assertGreater(grade.cases_total, 0)
        self.assertEqual(grade.cases_total, grade.cases_passed)

    def test_compiling_but_wrong_candidate_fails(self):
        # Same signatures, wrong semantics: nearly every case must disagree.
        # Exactly one case legitimately passes (empty input never enters the
        # loop), which is why the assertion is on the failure rate, not zero.
        wrong = _ground_truth_source(self.task)["target.cpp"].replace(
            "h *= kPrime;", "h += kPrime;")
        with Grader(self.task) as grader:
            grade = grader.grade({"target.cpp": wrong})
        self.assertFalse(grade.passed)
        self.assertGreaterEqual(grade.cases_total - grade.cases_passed,
                                grade.cases_total - 1)

    def test_empty_candidate_fails_to_build(self):
        with Grader(self.task) as grader:
            grade = grader.grade({"target.cpp": "// nothing here\n"})
        self.assertFalse(grade.passed)
        self.assertEqual(grade.stage, "build")

    def test_unexpected_source_name_rejected(self):
        sources = _ground_truth_source(self.task)
        sources["../../etc/passwd"] = "x"
        with Grader(self.task) as grader:
            grade = grader.grade(sources)
        self.assertFalse(grade.passed)
        self.assertIn("unexpected source", grade.reason)

    def test_missing_required_source_rejected(self):
        with Grader(self.task) as grader:
            grade = grader.grade({})
        self.assertFalse(grade.passed)
        self.assertIn("omitted required source", grade.reason)


class SchemaTests(unittest.TestCase):
    def test_hash_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(TASK_DIR, copy)
            (copy / "grader" / "properties.cpp").write_text(
                "// tampered\n", encoding="utf-8")
            with self.assertRaises(TaskError) as ctx:
                load_task(copy)
            self.assertIn("hash mismatch", str(ctx.exception))

    def test_missing_manifest_key_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(TASK_DIR, copy)
            manifest = json.loads((copy / "task.json").read_text())
            del manifest["driver"]
            manifest["content_hash"] = ""
            (copy / "task.json").write_text(json.dumps(manifest))
            with self.assertRaises(TaskError) as ctx:
                load_task(copy, verify_hash=False)
            self.assertIn("driver", str(ctx.exception))

    def test_path_traversal_rejected(self):
        task = load_task(TASK_DIR)
        with self.assertRaises(TaskError):
            task.path("../../../etc/passwd")

    def test_hash_is_line_ending_stable(self):
        """A CRLF checkout must hash the same as an LF checkout.

        Without normalisation the same commit produces different hashes on
        Windows and Linux, so CI fails on every run for no real reason.
        """
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(TASK_DIR, copy)
            for path in copy.rglob("*"):
                if path.is_file():
                    data = path.read_bytes().replace(b"\r\n", b"\n")
                    path.write_bytes(data.replace(b"\n", b"\r\n"))
            crlf_task = load_task(copy, verify_hash=False)
            self.assertEqual(crlf_task.computed_hash(),
                             load_task(TASK_DIR).computed_hash())


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(TASK_DIR)

    def _runner(self, tmp: str) -> Runner:
        return Runner(repo_root=REPO_ROOT, out_dir=Path(tmp))

    def test_replay_of_ground_truth_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(tmp)
            records = runner.run([self.task],
                                 [ReplayAgent(_ground_truth_source(self.task))],
                                 profile="baseline")
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0].grade.passed, records[0].grade.reason)
            self.assertEqual(records[0].adversary, "n/a (test double)")
            self.assertEqual(records[0].ledger.get("ledger_source"),
                             "self-reported by adapter")

    def test_stub_agent_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run([self.task], [StubAgent()],
                                            profile="baseline")
            self.assertFalse(records[0].grade.passed)

    def test_adapter_failure_is_recorded_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run([self.task], [BrokenAgent()],
                                            profile="baseline")
            self.assertEqual(records[0].grade.stage, "agent")
            self.assertIn("simulated adapter failure", records[0].error)

    def test_workspace_excludes_hidden_material(self):
        seen: dict[str, list[str]] = {}

        class Spy(ReplayAgent):
            def solve(self, task, workspace):
                seen["files"] = sorted(
                    p.relative_to(workspace).as_posix()
                    for p in workspace.rglob("*") if p.is_file())
                return super().solve(task, workspace)

        with tempfile.TemporaryDirectory() as tmp:
            self._runner(tmp).run([self.task],
                                  [Spy(_ground_truth_source(self.task))],
                                  profile="baseline")
        files = seen["files"]
        self.assertIn("task.md", files)
        self.assertIn("include/target.h", files)
        for path in files:
            self.assertNotIn("ground_truth", path)
            self.assertNotIn("grader", path)
            self.assertNotIn("hidden", path)

    def test_reports_carry_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run([self.task],
                                             [StubAgent()], profile="baseline")
            paths = write_reports(records, Path(tmp))
            rows = [json.loads(line) for line in
                    paths["jsonl"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            for key in ("task_hash", "profile", "agent", "environment",
                        "budgets", "grade"):
                self.assertIn(key, row)
            self.assertEqual(row["task_hash"], self.task.content_hash)
            self.assertIn("commit", row["environment"])
            markdown = paths["markdown"].read_text(encoding="utf-8")
            self.assertIn("self-reported by the adapter", markdown)


if __name__ == "__main__":
    unittest.main()
