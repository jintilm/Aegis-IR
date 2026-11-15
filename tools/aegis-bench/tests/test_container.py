"""Container isolation command and lifecycle tests."""

from __future__ import annotations

import json
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

from aegis_bench.agent import create_agent  # noqa: E402
from aegis_bench.audit import audit_path  # noqa: E402
from aegis_bench.campaign import load_experiment, run_campaign  # noqa: E402
from aegis_bench.container import (  # noqa: E402
    ContainerConfig, ContainerError, build_command, container_env)
from aegis_bench.grader import Grade  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import load_task  # noqa: E402

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


def _fake_runtime(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["AEGIS_FAKE_RUNTIME_LOG"])
if args[:2] == ["image", "inspect"]:
    raise SystemExit(0)
if args[:1] == ["rm"]:
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"remove": args}) + "\\n")
    raise SystemExit(0)
if args[:1] != ["run"]:
    raise SystemExit(2)
transport = None
env_file = None
for index, value in enumerate(args):
    if value == "--env-file":
        env_file = Path(args[index + 1])
    if value == "--mount":
        spec = args[index + 1]
        fields = dict(part.split("=", 1) for part in spec.split(",")
                      if "=" in part)
        if fields.get("target") == "/aegis/transport":
            transport = Path(fields["source"])
if transport is None:
    raise SystemExit(3)
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "run": args,
        "env_file_inside_transport": bool(
            env_file and str(env_file.resolve()).startswith(
                str(transport.resolve()))),
    }) + "\\n")
response = {
    "ok": True,
    "sources": {"target.cpp": "extern \\"C\\" int unused;\\n"},
    "ledger": {"tokens": 0},
    "notes": "fake container runtime",
    "isolation": {
        "adapter": "container",
        "sandbox": True,
        "filesystem": "container read-only root",
        "network": "container network disabled",
        "network_namespace": True,
    },
}
(transport / "response.json").write_text(
    json.dumps(response), encoding="utf-8")
""",
        encoding="utf-8")
    path.chmod(0o755)


class ContainerCommandTests(unittest.TestCase):
    def test_command_enforces_security_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            transport = root / "transport"
            package = root / "bench"
            adapters = root / "adapters"
            for path in (workspace, transport, package, adapters):
                path.mkdir()
            env_file = root / "container.env"
            env_file.write_text("PYTHONPATH=/aegis/bench\n",
                                encoding="utf-8")
            config = ContainerConfig(
                runtime="docker", image="aegis-ir-dev",
                user="65534:65534")
            with patch("aegis_bench.container.shutil.which",
                       return_value="/usr/bin/docker"):
                command = build_command(
                    config, name="aegis-test", workspace=workspace,
                    transport=transport, package_root=package,
                    adapter_mounts=((adapters, "/aegis/adapters/0"),),
                    broker_socket=str(root / "broker.sock"),
                    meter_socket=str(root / "meter.sock"),
                    env_file=env_file,
                    worker_args=("/aegis/transport/request.json",
                                 "/aegis/transport/response.json",
                                 "/aegis/workspace"))
        joined = " ".join(command)
        self.assertIn("--read-only", command)
        self.assertIn("--network=none", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--security-opt=no-new-privileges:true", command)
        self.assertIn("--pids-limit=128", command)
        self.assertIn("--memory=1g", command)
        self.assertIn("--user 65534:65534", joined)
        self.assertNotIn("--privileged", command)
        self.assertNotIn("/var/run/docker.sock", joined)
        self.assertIn("target=/aegis/workspace", joined)
        self.assertIn("target=/aegis/bench,readonly", joined)

    def test_container_env_is_an_explicit_allowlist(self):
        with patch.dict(os.environ, {
            "LLM_API_KEY": "test-key",
            "UNRELATED_SECRET": "must-not-pass",
        }, clear=False):
            env = container_env()
        self.assertEqual(env["LLM_API_KEY"], "test-key")
        self.assertNotIn("UNRELATED_SECRET", env)

    def test_missing_runtime_fails_preflight(self):
        config = ContainerConfig(runtime="definitely-missing-runtime")
        with patch("aegis_bench.container.shutil.which", return_value=None):
            with self.assertRaises(ContainerError):
                config.preflight()


class ContainerRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(TASK_ROOT)

    def test_runner_uses_container_proxy_and_records_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "fake-container"
            _fake_runtime(runtime)
            log = root / "runtime.log"
            with patch.dict(os.environ, {
                "AEGIS_CONTAINER_RUNTIME": str(runtime),
                "AEGIS_CONTAINER_USER": "65534:65534",
                "AEGIS_FAKE_RUNTIME_LOG": str(log),
            }), patch("aegis_bench.runner.Grader", _FakeGrader):
                records = Runner(
                    repo_root=REPO_ROOT, out_dir=root / "out",
                    adapter_isolation="container").run(
                        [self.task], [create_agent("broker-stub")],
                        profile="baseline")
            record = records[0]
            self.assertTrue(record.grade.passed, record.grade.reason)
            self.assertEqual(record.isolation["adapter"], "container")
            self.assertTrue(record.isolation["network_namespace"])
            self.assertTrue(record.isolation["sandbox"])
            self.assertEqual(
                record.isolation["container"]["network"], "none")
            logged = log.read_text(encoding="utf-8")
            self.assertIn('"run"', logged)
            self.assertIn("--network=none", logged)
            self.assertNotIn("LLM_API_KEY", logged)
            self.assertIn('"env_file_inside_transport": false', logged)

    def test_campaign_audit_requires_the_container_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "fake-container"
            _fake_runtime(runtime)
            log = root / "runtime.log"
            manifest = root / "experiment.json"
            out = root / "out"
            manifest.write_text(json.dumps({
                "schema_version": 2,
                "name": "container-audit",
                "purpose": "harness-validation",
                "primary_metric": "pass_rate",
                "tasks_root": str(TASK_ROOT.parent),
                "tasks": ["rolling-token-v1"],
                "agents": [{
                    "id": "stub",
                    "adapter": "stub",
                    "expected_version": "builtin-test-double-v1",
                }],
                "profiles": ["baseline"],
                "repetitions": 1,
                "access": "oracle",
                "order": "sequential",
                "seed": 1,
                "require_clean": False,
                "require_meter": False,
                "require_broker_tools": False,
                "adapter_isolation": "container",
                "require_sandbox": True,
                "require_network_namespace": True,
                "allow_oracle_comparison": False,
                "out": str(out),
            }), encoding="utf-8")
            experiment = load_experiment(manifest)
            with patch.dict(os.environ, {
                "AEGIS_CONTAINER_RUNTIME": str(runtime),
                "AEGIS_CONTAINER_USER": "65534:65534",
                "AEGIS_CONTAINER_SKIP_IMAGE_CHECK": "1",
                "AEGIS_FAKE_RUNTIME_LOG": str(log),
            }), patch("aegis_bench.runner.Grader", _FakeGrader):
                run_campaign(
                    experiment, repo_root=REPO_ROOT, out_dir=out)
            report = audit_path(out, experiment=experiment)
            self.assertFalse(
                [issue for issue in report.issues
                 if issue.code == "container-boundary"], report.issues)

            data = out / "aegis-bench.jsonl"
            row = json.loads(data.read_text(encoding="utf-8"))
            row["isolation"]["container"]["non_root"] = False
            data.write_text(json.dumps(row) + "\n", encoding="utf-8")
            report = audit_path(out, experiment=experiment)
            self.assertTrue(any(
                issue.code == "container-boundary"
                for issue in report.errors), report.issues)


if __name__ == "__main__":
    unittest.main()
