"""Tests for the process-isolated adapter worker boundary."""

from __future__ import annotations

import os
import socket
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
from aegis_bench.landlock import abi_version  # noqa: E402
from aegis_bench.netns import NetnsError, unshare_options  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import TaskError, load_task  # noqa: E402
from aegis_bench.seccomp import available as seccomp_available  # noqa: E402
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
        expected_sandbox = os.name == "posix" and abi_version() > 0
        self.assertEqual(record.isolation["sandbox"], expected_sandbox)
        self.assertEqual(record.tools["requests"], 3)

    def test_process_isolation_recreates_model_options(self):
        agent = create_agent(
            "model-stub", model="deepseek-flash")
        with tempfile.TemporaryDirectory() as tmp, \
                patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp),
                adapter_isolation="process").run(
                    [self.task], [agent], profile="baseline")
        record = records[0]
        self.assertEqual(record.agent, "model-stub-deepseek-flash")
        self.assertEqual(record.agent_config, {"model": "deepseek-flash"})

    def test_landlock_denies_forbidden_host_path(self):
        if os.name != "posix" or abi_version() <= 0:
            self.skipTest("Landlock unavailable")
        agent = create_agent("forbidden-read")
        forbidden = REPO_ROOT / "README.md"
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {
                    "AEGIS_TEST_FORBIDDEN_PATH": str(forbidden),
                }), patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp),
                adapter_isolation="process").run(
                    [self.task], [agent], profile="baseline")
        record = records[0]
        self.assertTrue(record.grade.passed, record.grade.reason)
        self.assertTrue(record.isolation["sandbox"])

    def test_landlock_denies_unapproved_tcp_port(self):
        if os.name != "posix" or abi_version() <= 0:
            self.skipTest("Landlock unavailable")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        agent = create_agent("forbidden-connect")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {
                    "AEGIS_TEST_FORBIDDEN_PORT": str(port),
                }), patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp),
                adapter_isolation="process").run(
                    [self.task], [agent], profile="baseline")
        record = records[0]
        self.assertTrue(record.grade.passed, record.grade.reason)
        self.assertTrue(record.isolation["sandbox"])

    def test_seccomp_denies_udp_socket(self):
        if (os.name != "posix" or abi_version() <= 0
                or not seccomp_available()):
            self.skipTest("Landlock/seccomp unavailable")
        agent = create_agent("forbidden-udp")
        with tempfile.TemporaryDirectory() as tmp, \
                patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp),
                adapter_isolation="process").run(
                    [self.task], [agent], profile="baseline")
        record = records[0]
        self.assertTrue(record.grade.passed, record.grade.reason)
        self.assertTrue(record.isolation["sandbox"])
        self.assertIn("UDP", record.isolation["network"])

    def test_network_namespace_blocks_host_egress_and_bridges_broker(self):
        if os.name != "posix":
            self.skipTest("network namespaces are Linux-only")
        try:
            unshare_options()
        except NetnsError as exc:
            self.skipTest(str(exc))
        route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            route_probe.connect(("1.1.1.1", 53))
            host = route_probe.getsockname()[0]
        except OSError as exc:
            self.skipTest(f"no host route to derive test address: {exc}")
        finally:
            route_probe.close()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((host, 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]

        with tempfile.TemporaryDirectory() as tmp:
            egress = create_agent("forbidden-egress")
            with patch.dict(os.environ, {
                "AEGIS_TEST_HOST_ADDRESS": host,
                "AEGIS_TEST_HOST_PORT": str(port),
            }), patch("aegis_bench.runner.Grader", _FakeGrader):
                records = Runner(
                    repo_root=REPO_ROOT, out_dir=Path(tmp),
                    adapter_isolation="process",
                    network_namespace=True).run(
                        [self.task], [egress], profile="baseline")
            self.assertTrue(records[0].grade.passed, records[0].grade.reason)
            self.assertTrue(
                records[0].isolation["network_namespace"],
                records[0].isolation)
            self.assertIn("private network namespace",
                          records[0].isolation["network"])

        with tempfile.TemporaryDirectory() as tmp:
            agent = create_agent("broker-stub")
            with patch("aegis_bench.runner.Grader", _FakeGrader):
                records = Runner(
                    repo_root=REPO_ROOT, out_dir=Path(tmp),
                    adapter_isolation="process",
                    network_namespace=True).run(
                        [self.task], [agent], profile="baseline")
            self.assertTrue(records[0].grade.passed, records[0].grade.reason)
            self.assertEqual(records[0].tools["requests"], 3)

    def test_network_namespace_meter_bridge_preserves_base_path(self):
        if os.name != "posix":
            self.skipTest("network namespaces are Linux-only")
        try:
            unshare_options()
        except NetnsError as exc:
            self.skipTest(str(exc))
        agent = create_agent("meter-path", suffix="/v1")
        with tempfile.TemporaryDirectory() as tmp, \
                patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT, out_dir=Path(tmp),
                adapter_isolation="process",
                network_namespace=True,
                meter_upstream="https://relay.example/v1").run(
                    [self.task], [agent], profile="baseline")
        record = records[0]
        self.assertTrue(record.grade.passed, record.grade.reason)
        self.assertTrue(record.isolation["network_namespace"])


if __name__ == "__main__":
    unittest.main()
