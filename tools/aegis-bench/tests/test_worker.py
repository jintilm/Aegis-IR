"""Tests for the process-isolated adapter worker boundary."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
REPO_ROOT = TOOL_ROOT.parents[1]
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.agent import create_agent  # noqa: E402
from aegis_bench.grader import Grade  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import TaskError, load_task  # noqa: E402
from aegis_bench.worker import TaskView  # noqa: E402

TASK_ROOT = REPO_ROOT / "benchmarks" / "tasks-public" / "rolling-token-v1"


class _FakeGrader:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def grade(self, _sources):
        return Grade(True, "ok", "fake grader", 1, 1)


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(TASK_ROOT)

    def test_task_view_hides_grader_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            view = TaskView.from_task(self.task, Path(tmp))
            with self.assertRaises(TaskError):
                view.path("ground_truth/target.cpp")
            with self.assertRaises(TaskError):
                view.path("grader/hidden/cases.json")
            self.assertEqual(
                view.path("task.md").name, "task.md")

    def test_process_isolation_runs_an_importable_agent(self):
        agent = create_agent("broker-stub")
        with tempfile.TemporaryDirectory() as tmp, \
                patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp),
                adapter_isolation="process").run(
                    [self.task], [agent], profile="baseline")
        record = records[0]
        self.assertTrue(record.grade.passed, record.grade.reason)
        self.assertEqual(record.isolation["adapter"], "process")
        self.assertFalse(record.isolation["sandbox"])
        self.assertEqual(record.tools["requests"], 3)


if __name__ == "__main__":
    unittest.main()
