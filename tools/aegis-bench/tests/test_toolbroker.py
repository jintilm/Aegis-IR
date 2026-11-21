"""Tests for the harness-owned workspace tool broker."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
REPO_ROOT = TOOL_ROOT.parents[1]
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.agent import Agent, AgentResult  # noqa: E402
from aegis_bench.artifact import BuiltArtifact  # noqa: E402
from aegis_bench.grader import Grade  # noqa: E402
from aegis_bench.oracle import OracleBroker, query  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import load_task  # noqa: E402
from aegis_bench.toolbroker import (  # noqa: E402
    BROKER_ENV_TOKEN, BROKER_ENV_URL, ToolBroker, ToolDenied, ToolError,
    call_tool)

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

    @staticmethod
    def _artifact(path: Path) -> BuiltArtifact:
        path.write_text("print('trusted probe')\n", encoding="utf-8")
        data = path.read_bytes()
        return BuiltArtifact(
            profile="baseline", level=0, path=path,
            sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
            text_bytes=0, toolchain={}, build_log="test fixture")

    def test_workspace_probe_is_never_an_implicit_execution_target(self):
        tmp, workspace = self._workspace()
        self.addCleanup(tmp.cleanup)
        broker = ToolBroker(
            workspace=workspace, task=self.task, access="binary")
        with self.assertRaisesRegex(ToolError, "no trusted probe"):
            broker.dispatch("run_probe", {})
        with self.assertRaisesRegex(ValueError, "outside the workspace"):
            ToolBroker(workspace=workspace, task=self.task, access="binary",
                       trusted_probe=workspace / "probe")

    def test_workspace_replacement_does_not_change_probe_or_disassembly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            private = root / "private"
            private.mkdir()
            artifact = self._artifact(root / "original.py")
            frozen = artifact.snapshot(private)
            broker = ToolBroker(
                workspace=workspace, task=self.task, access="binary",
                trusted_probe=frozen.path,
                probe_command=[sys.executable, str(frozen.path)],
                enable_disassembly=True)
            (workspace / "probe").write_text(
                "print('workspace replacement')\n", encoding="utf-8")
            artifact.path.write_text(
                "print('cache replacement')\n", encoding="utf-8")
            response = broker.dispatch("run_probe", {})
            self.assertIn("trusted probe", response)
            self.assertNotIn("replacement", response)
            with patch("aegis_bench.toolbroker.shutil.which",
                       return_value="objdump-test"), \
                    patch("aegis_bench.toolbroker.run_bounded",
                          return_value=subprocess.CompletedProcess(
                              [], 0, b"0000 <test>:\n  0: ret\n", b"")) as run:
                broker.dispatch("disassemble", {})
            self.assertEqual(run.call_args.args[0][-1], str(frozen.path))

    def test_oracle_calls_use_the_counted_service_without_executing_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = self._artifact(root / "probe.py")
            (workspace / "probe").write_text(
                "print('unrelated workspace file')\n", encoding="utf-8")
            with OracleBroker(
                    [sys.executable, str(artifact.path)], budget=1) as oracle:
                broker = ToolBroker(
                    workspace=workspace, task=self.task, access="oracle",
                    oracle_query=partial(query, oracle.address,
                                         transport=oracle.transport))
                self.assertIn("trusted probe", broker.dispatch("run_probe", {}))
                with self.assertRaisesRegex(ToolError, "oracle budget exhausted"):
                    broker.dispatch("run_probe", {})
                self.assertEqual(oracle.stats.queries, 1)
                self.assertEqual(oracle.stats.refused, 1)

    def test_runner_binds_private_snapshot_and_preserves_oracle_accounting(self):
        source = self.task.path(self.task.ground_truth).read_text(encoding="utf-8")
        for access in ("binary", "oracle"):
            with self.subTest(access=access), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                artifact = self._artifact(root / "probe.py")
                bound_paths = []
                seen = []
                task = self.task
                if access == "oracle":
                    task = replace(task, budgets=replace(
                        task.budgets, oracle_queries=1))

                class FixtureRunner(Runner):
                    def artifact_for(self, _task, _profile):
                        return artifact

                    def _probe_command(self, frozen):
                        bound_paths.append(frozen.path)
                        return [sys.executable, str(frozen.path)]

                class WorkspaceEditingAgent(Agent):
                    name = "workspace-editor"
                    version = "test-v1"

                    def solve(self, task, workspace):
                        (workspace / "probe").write_text(
                            "print('workspace replacement')\n", encoding="utf-8")
                        artifact.path.write_text(
                            "print('cache replacement')\n", encoding="utf-8")
                        seen.append(call_tool("run_probe", {}))
                        if access == "oracle":
                            try:
                                call_tool("run_probe", {})
                            except ToolError as exc:
                                seen.append(str(exc))
                        return AgentResult(
                            sources={task.candidate_sources[0]: source},
                            ledger={"tool_calls": 2 if access == "oracle" else 1})

                with patch("aegis_bench.runner.Grader", _FakeGrader):
                    record = FixtureRunner(
                        repo_root=REPO_ROOT, out_dir=root / "out",
                        access=access).run(
                            [task], [WorkspaceEditingAgent()],
                            profile="baseline")[0]
                self.assertTrue(record.grade.passed, record.error)
                self.assertIn("trusted probe", seen[0])
                self.assertNotIn("replacement", seen[0])
                self.assertTrue(bound_paths)
                self.assertTrue(all(not path.exists() for path in bound_paths))
                if access == "oracle":
                    self.assertIn("oracle budget exhausted", seen[1])
                    self.assertEqual(record.oracle["queries"], 1)
                    self.assertEqual(record.oracle["refused"], 1)
                else:
                    self.assertIsNone(record.oracle["queries"])

    def _wait_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("timed out waiting for the fixture to start")
            time.sleep(0.01)

    def test_stop_cancels_active_probe_before_returning_final_counters(self):
        for access in ("binary", "oracle"):
            with self.subTest(access=access), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = root / "workspace"
                workspace.mkdir()
                marker = root / "started"
                probe = root / "slow.py"
                probe.write_text(
                    "import os, time\nfrom pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
                    "time.sleep(30)\n", encoding="utf-8")
                command = [sys.executable, str(probe)]
                oracle = (OracleBroker(command).start()
                          if access == "oracle" else None)
                broker = ToolBroker(
                    workspace=workspace, task=self.task, access=access,
                    trusted_probe=probe, probe_command=command,
                    oracle_query=(partial(query, oracle.address,
                                          transport=oracle.transport)
                                  if oracle is not None else None),
                    oracle_cancel=(oracle.cancel
                                   if oracle is not None else None)).start()
                result = []
                url, token = broker.url, broker.token

                def client():
                    try:
                        result.append(call_tool("run_probe", {}, url=url,
                                                token=token, timeout=10))
                    except ToolError as exc:
                        result.append(exc)

                caller = threading.Thread(target=client)
                caller.start()
                try:
                    self._wait_until(marker.is_file)
                    started = time.monotonic()
                    stats = broker.stop()
                    if oracle is not None:
                        oracle.stop()
                    self.assertLess(time.monotonic() - started, 5)
                    caller.join(timeout=2)
                    self.assertFalse(caller.is_alive())
                    self.assertFalse(broker._connections)
                    self.assertEqual(stats, broker.stats.to_dict())
                    self.assertEqual(stats["requests"], 1)
                    self.assertEqual(stats["failed"], 1)
                    if oracle is not None:
                        self.assertEqual(oracle.stats.queries, 1)
                        self.assertEqual(oracle.stats.failed, 1)
                    if os.name == "posix":
                        with self.assertRaises(ProcessLookupError):
                            os.kill(int(marker.read_text()), 0)
                finally:
                    broker.stop()
                    if oracle is not None:
                        oracle.stop()
                    caller.join(timeout=2)

    def test_stop_interrupts_incomplete_http_and_oracle_requests(self):
        tmp, workspace = self._workspace()
        self.addCleanup(tmp.cleanup)
        broker = ToolBroker(
            workspace=workspace, task=self.task, access="binary").start()
        conn = socket.create_connection(("127.0.0.1", broker.port), timeout=2)
        try:
            conn.sendall(b"POST /call HTTP/1.0\r\nContent-Length: 100\r\n\r\n{")
            self._wait_until(lambda: bool(broker._connections))
            started = time.monotonic()
            broker.stop()
            self.assertLess(time.monotonic() - started, 2)
            self.assertFalse(broker._connections)
            self.assertEqual(broker.stats.requests, 0)
        finally:
            conn.close()
            broker.stop()

        oracle = OracleBroker([sys.executable, "-c", "print('unused')"]).start()
        if oracle.transport == "unix":
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.connect(oracle.address)
        else:
            host, _, port = oracle.address.rpartition(":")
            conn = socket.create_connection((host, int(port)), timeout=2)
        try:
            conn.sendall(b'{"protocol":')
            self._wait_until(lambda: oracle._connection is not None)
            started = time.monotonic()
            oracle.stop()
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNone(oracle._thread)
            self.assertIsNone(oracle._connection)
            self.assertEqual(oracle.stats.queries, 0)
        finally:
            conn.close()
            oracle.stop()


if __name__ == "__main__":
    unittest.main()
