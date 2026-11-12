"""Tests for the harness-owned workspace tool broker."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
REPO_ROOT = TOOL_ROOT.parents[1]
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.agent import Agent, AgentResult  # noqa: E402
from aegis_bench.grader import Grade  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import load_task  # noqa: E402
from aegis_bench.toolbroker import (  # noqa: E402
    BROKER_ENV_TOKEN, BROKER_ENV_URL, ToolBroker, ToolDenied, call_tool)

TASKS_ROOT = REPO_ROOT / "benchmarks" / "tasks-public"
REIMPLEMENT_DIR = TASKS_ROOT / "rolling-token-v1"
BINARY_DIR = TASKS_ROOT / "rolling-token-v2"


class _FakeGrader:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def grade(self, _sources):
        return Grade(True, "ok", "fake grader", 1, 1)


class BrokerAgent(Agent):
    name = "broker-test"
    version = "broker-test-v1"
    adversary = "n/a (tool broker test)"

    def __init__(self, source: str):
        self.source = source
        self.seen: list[str] = []

    def solve(self, task, workspace):
        self.seen.append(call_tool("list_files", {}))
        self.seen.append(call_tool(
            "read_file", {"path": "task.md"}))
        self.seen.append(call_tool(
            "submit_solution", {"source": self.source}))
        return AgentResult(
            sources={task.candidate_sources[0]: self.source},
            ledger={"tokens": None, "tool_calls": len(self.seen)})


class ToolBrokerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

    def _workspace(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory()
        workspace = Path(tmp.name)
        (workspace / "task.md").write_text(
            "visible task", encoding="utf-8")
        (workspace / "probe").write_text(
            "#!/bin/sh\necho probe\n", encoding="utf-8")
        (workspace / "probe").chmod(0o755)
        return tmp, workspace

    def test_http_broker_counts_and_contains_paths(self):
        tmp, workspace = self._workspace()
        self.addCleanup(tmp.cleanup)
        broker = ToolBroker(
            workspace=workspace, task=self.task, access="binary",
            max_calls=5, enable_disassembly=False).start()
        try:
            listing = call_tool(
                "list_files", {}, url=broker.url, token=broker.token)
            text = call_tool(
                "read_file", {"path": "task.md"},
                url=broker.url, token=broker.token)
            with self.assertRaises(ToolDenied):
                call_tool(
                    "read_file", {"path": "../outside"},
                    url=broker.url, token=broker.token)
        finally:
            stats = broker.stop(reported_by_adapter=4)
        self.assertIn("task.md", listing)
        self.assertEqual(text, "visible task")
        self.assertEqual(stats["requests"], 3)
        self.assertEqual(stats["denied"], 1)
        self.assertEqual(stats["calls_by_tool"]["read_file"], 2)
        self.assertTrue(stats["adapter_exceeds_broker"])

    def test_budget_and_disassembly_policy_are_enforced(self):
        tmp, workspace = self._workspace()
        self.addCleanup(tmp.cleanup)
        broker = ToolBroker(
            workspace=workspace, task=self.task, access="oracle",
            max_calls=1, enable_disassembly=False).start()
        try:
            call_tool("list_files", {}, url=broker.url, token=broker.token)
            with self.assertRaises(ToolDenied):
                call_tool(
                    "list_files", {}, url=broker.url, token=broker.token)
        finally:
            stats = broker.stop()
        self.assertEqual(stats["allowed"], 1)
        self.assertEqual(stats["denied"], 1)
        self.assertIn("tool-call budget", stats["denials"][0]["reason"])

        oracle_broker = ToolBroker(
            workspace=workspace, task=self.task, access="oracle",
            max_calls=2, enable_disassembly=False).start()
        try:
            with self.assertRaises(ToolDenied):
                call_tool(
                    "disassemble", {"offset": 0},
                    url=oracle_broker.url, token=oracle_broker.token)
        finally:
            oracle_stats = oracle_broker.stop()
        self.assertIn("binary access",
                      oracle_stats["denials"][0]["reason"])

    def test_runner_injects_broker_and_cleans_environment(self):
        task = load_task(REIMPLEMENT_DIR)
        source = task.path(task.ground_truth).read_text(encoding="utf-8")
        agent = BrokerAgent(source)
        with tempfile.TemporaryDirectory() as tmp, \
                patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp)).run(
                    [task], [agent], profile="baseline")
        record = records[0]
        self.assertTrue(record.grade.passed)
        self.assertEqual(record.tools["requests"], 3)
        self.assertEqual(record.tools["calls_by_tool"], {
            "list_files": 1,
            "read_file": 1,
            "submit_solution": 1,
        })
        self.assertEqual(record.tools["source"], "harness tool broker")
        self.assertNotIn(BROKER_ENV_URL, os.environ)
        self.assertNotIn(BROKER_ENV_TOKEN, os.environ)


if __name__ == "__main__":
    unittest.main()
