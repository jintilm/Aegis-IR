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
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.adapters.fake import (  # noqa: E402
    BrokenAgent, ProbeQueryAgent, ReplayAgent, StubAgent)
from aegis_bench.artifact import ArtifactError, BuiltArtifact  # noqa: E402
from aegis_bench.grader import Grade, Grader  # noqa: E402
from aegis_bench.oracle import (  # noqa: E402
    OracleBroker, OracleError, install_shim, query)
from aegis_bench.report import wilson_interval, write_markdown, write_reports  # noqa: E402
from aegis_bench.runner import RunRecord, Runner  # noqa: E402
from aegis_bench.schema import Budget, TaskError, discover_tasks, load_task  # noqa: E402

REPO_ROOT = TOOL_ROOT.parents[1]
TASKS_ROOT = REPO_ROOT / "benchmarks" / "tasks-public"
# Two task shapes are exercised: the frozen reimplementation task (grader and
# schema behaviour) and the binary-recovery task (artifact builds).
REIMPLEMENT_DIR = TASKS_ROOT / "rolling-token-v1"
BINARY_DIR = TASKS_ROOT / "rolling-token-v2"
AEGIS_PLUGIN = os.environ.get("AEGIS_PLUGIN") or None


def _ground_truth_source(task) -> dict[str, str]:
    return {"target.cpp": task.path(task.ground_truth).read_text(encoding="utf-8")}


class GraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(REIMPLEMENT_DIR)

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
            shutil.copytree(REIMPLEMENT_DIR, copy)
            (copy / "grader" / "properties.cpp").write_text(
                "// tampered\n", encoding="utf-8")
            with self.assertRaises(TaskError) as ctx:
                load_task(copy)
            self.assertIn("hash mismatch", str(ctx.exception))

    def test_missing_manifest_key_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(REIMPLEMENT_DIR, copy)
            manifest = json.loads((copy / "task.json").read_text())
            del manifest["driver"]
            manifest["content_hash"] = ""
            (copy / "task.json").write_text(json.dumps(manifest))
            with self.assertRaises(TaskError) as ctx:
                load_task(copy, verify_hash=False)
            self.assertIn("driver", str(ctx.exception))

    def test_path_traversal_rejected(self):
        task = load_task(REIMPLEMENT_DIR)
        with self.assertRaises(TaskError):
            task.path("../../../etc/passwd")

    def test_calibration_record_is_validated(self):
        """A floor/ceiling/comparison-ready label must match its own number."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(BINARY_DIR, copy)
            manifest = json.loads((copy / "task.json").read_text())

            def load_with(calibration):
                manifest["calibration"] = calibration
                (copy / "task.json").write_text(json.dumps(manifest))
                return load_task(copy, verify_hash=False)

            task = load_with({"oracle": {
                "status": "floor", "model": "m", "baseline_pass_rate": 0.0,
                "runs": 3, "date": "2026-11-11"}})
            self.assertEqual(task.calibration["oracle"].status, "floor")
            # A floor label with a non-zero rate is a contradiction, not data.
            with self.assertRaises(TaskError):
                load_with({"oracle": {"status": "floor", "model": "m",
                                      "baseline_pass_rate": 0.4, "runs": 3,
                                      "date": "2026-11-11"}})
            with self.assertRaises(TaskError):
                load_with({"oracle": {"status": "comparison-ready", "model": "m",
                                      "baseline_pass_rate": 1.0, "runs": 5,
                                      "date": "2026-11-11"}})
            # Calibration is per access mode; a bare status is not a mode.
            with self.assertRaises(TaskError):
                load_with({"status": "floor"})
            with self.assertRaises(TaskError):
                load_with({"shim": {"status": "floor"}})
            with self.assertRaises(TaskError):
                load_with({"oracle": {"status": "meaningful"}})

    def test_calibration_is_outside_the_content_hash(self):
        """Calibration is measurement metadata; adding it must not rename a task."""
        plain = load_task(BINARY_DIR, verify_hash=False)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(BINARY_DIR, copy)
            manifest = json.loads((copy / "task.json").read_text())
            manifest["calibration"] = {"binary": {
                "status": "comparison-ready", "model": "m",
                "baseline_pass_rate": 0.5, "runs": 5, "date": "2026-11-11"}}
            (copy / "task.json").write_text(json.dumps(manifest))
            calibrated = load_task(copy, verify_hash=False)
            calibrated_hash = calibrated.computed_hash()
        self.assertEqual(plain.computed_hash(), calibrated_hash)

    def test_hash_is_line_ending_stable(self):
        """A CRLF checkout must hash the same as an LF checkout.

        Without normalisation the same commit produces different hashes on
        Windows and Linux, so CI fails on every run for no real reason.
        """
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "task"
            shutil.copytree(REIMPLEMENT_DIR, copy)
            for path in copy.rglob("*"):
                if path.is_file():
                    data = path.read_bytes().replace(b"\r\n", b"\n")
                    path.write_bytes(data.replace(b"\n", b"\r\n"))
            crlf_task = load_task(copy, verify_hash=False)
            self.assertEqual(crlf_task.computed_hash(),
                             load_task(REIMPLEMENT_DIR).computed_hash())


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

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
        self.assertIn("probe", files)
        for path in files:
            self.assertNotIn("ground_truth", path)
            self.assertNotIn("grader", path)
            self.assertNotIn("hidden", path)

    def test_probe_is_executable(self):
        seen: dict[str, bool] = {}

        class Spy(ReplayAgent):
            def solve(self, task, workspace):
                probe = workspace / "probe"
                seen["exists"] = probe.is_file()
                seen["executable"] = os.access(probe, os.X_OK)
                return super().solve(task, workspace)

        with tempfile.TemporaryDirectory() as tmp:
            self._runner(tmp).run([self.task],
                                  [Spy(_ground_truth_source(self.task))],
                                  profile="baseline")
        self.assertTrue(seen["exists"])
        self.assertTrue(seen["executable"])

    def test_reports_carry_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run([self.task],
                                             [StubAgent()], profile="baseline")
            paths = write_reports(records, Path(tmp))
            rows = [json.loads(line) for line in
                    paths["jsonl"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            for key in ("task_hash", "profile", "agent", "adapter_version",
                        "environment", "budgets", "grade", "artifact"):
                self.assertIn(key, row)
            self.assertEqual(row["task_hash"], self.task.content_hash)
            self.assertIn("commit", row["environment"])
            self.assertEqual(row["artifact"]["level"], 0)
            self.assertEqual(len(row["artifact"]["sha256"]), 64)
            self.assertGreater(row["artifact"]["text_bytes"], 0)
            markdown = paths["markdown"].read_text(encoding="utf-8")
            self.assertIn("self-reported by the adapter", markdown)

    def test_adapter_version_is_recorded(self):
        class Versioned(StubAgent):
            name = "versioned"
            version = "abc123def456"

        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run([self.task], [Versioned()],
                                            profile="baseline")
            paths = write_reports(records, Path(tmp))
            row = json.loads(paths["jsonl"].read_text(
                encoding="utf-8").splitlines()[0])
            markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertEqual(records[0].adapter_version, "abc123def456")
        self.assertEqual(row["adapter_version"], "abc123def456")
        self.assertIn("abc123def456", markdown)

    def test_unknown_artifact_profile_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ArtifactError):
                self._runner(tmp).run([self.task], [StubAgent()],
                                      profile="not-a-profile")

    def test_missing_plugin_is_recorded_as_artifact_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(repo_root=REPO_ROOT, out_dir=Path(tmp),
                            plugin="")
            records = runner.run([self.task], [StubAgent()],
                                 profile="aegis-level1")
        self.assertEqual(records[0].grade.stage, "artifact")
        self.assertIn("plugin", records[0].error)


class CandidatePolicyTests(unittest.TestCase):
    """Oracle replay and grader-material access must be rejected before build."""

    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

    def _grade(self, sources):
        with Grader(self.task) as grader:
            return grader.grade(sources)

    def test_include_of_ground_truth_rejected(self):
        src = "#include " + chr(34) + "ground_truth/target.cpp" + chr(34) + chr(10)
        grade = self._grade({"target.cpp": src})
        self.assertFalse(grade.passed)
        self.assertEqual(grade.stage, "build")
        self.assertIn("policy", grade.reason)

    def test_absolute_include_rejected(self):
        src = "#include " + chr(34) + "/etc/passwd" + chr(34) + chr(10)
        grade = self._grade({"target.cpp": src})
        self.assertFalse(grade.passed)
        self.assertEqual(grade.stage, "build")
        self.assertIn("escapes", grade.reason)

    def test_parent_relative_include_rejected(self):
        src = "#include " + chr(34) + "../target.h" + chr(34) + chr(10)
        grade = self._grade({"target.cpp": src})
        self.assertFalse(grade.passed)
        self.assertEqual(grade.stage, "build")
        self.assertIn("escapes", grade.reason)

    def test_unknown_local_header_rejected(self):
        src = "#include " + chr(34) + "sneaky.h" + chr(34) + chr(10)
        grade = self._grade({"target.cpp": src})
        self.assertFalse(grade.passed)
        self.assertIn("not part of the task interface", grade.reason)

    def test_interface_header_allowed(self):
        src = "#include " + chr(34) + "target.h" + chr(34) + chr(10)
        grade = self._grade({"target.cpp": src})
        self.assertNotIn("policy", grade.reason)

    def test_exec_call_rejected(self):
        src = "#include <cstdlib>" + chr(10)
        src += "int f() { return system(" + chr(34) + "./probe" + chr(34) + "); }" + chr(10)
        grade = self._grade({"target.cpp": src})
        self.assertFalse(grade.passed)
        self.assertIn("standalone implementation", grade.reason)

    def test_oversized_source_rejected(self):
        src = "// " + "x" * (300 * 1024)
        grade = self._grade({"target.cpp": src})
        self.assertFalse(grade.passed)
        self.assertIn("bytes", grade.reason)


class AdapterTimeoutTests(unittest.TestCase):
    def test_slow_adapter_times_out(self):
        import time

        class Slow(StubAgent):
            name = "slow"

            def solve(self, task, workspace):
                time.sleep(5)
                return super().solve(task, workspace)

        task = load_task(REIMPLEMENT_DIR)
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(repo_root=REPO_ROOT, out_dir=Path(tmp),
                            adapter_timeout=1)
            records = runner.run([task], [Slow()], profile="baseline")
        self.assertFalse(records[0].grade.passed)
        self.assertEqual(records[0].grade.stage, "agent")
        self.assertIn("wall-clock budget", records[0].error)
        self.assertEqual(
            records[0].budgets["enforcement"]["adapter_timeout"],
            "enforced (SIGALRM)")


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

    def test_baseline_probe_matches_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(repo_root=REPO_ROOT, out_dir=Path(tmp))
            artifact = runner.artifact_for(self.task, "baseline")
            self.assertIsNotNone(artifact)
            proc = subprocess.run(
                [str(artifact.path)], input=b"aegis-ir",
                capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(
            proc.stdout.decode().strip(),
            "hash=10781158686979218516 checksum=232850194 verify=0")
        nm = shutil.which("nm")
        if nm:
            symbols = subprocess.run([nm, str(artifact.path)],
                                     capture_output=True, timeout=10)
            self.assertNotIn("bench_hash", symbols.stdout.decode(
                errors="replace"))

    def test_artifact_build_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(repo_root=REPO_ROOT, out_dir=Path(tmp))
            first = runner.artifact_for(self.task, "baseline")
            second = runner.artifact_for(self.task, "baseline")
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.path, second.path)

    @unittest.skipUnless(AEGIS_PLUGIN, "AEGIS_PLUGIN not set")
    def test_level3_probe_is_built_and_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(repo_root=REPO_ROOT, out_dir=Path(tmp),
                            plugin=AEGIS_PLUGIN)
            baseline = runner.artifact_for(self.task, "baseline")
            level3 = runner.artifact_for(self.task, "aegis-level3")
        self.assertEqual(level3.level, 3)
        self.assertIn("[aegis-cff] flattened", level3.build_log)
        self.assertIn("[aegis-verify] OK", level3.build_log)
        self.assertNotEqual(baseline.sha256, level3.sha256)
        self.assertGreater(level3.text_bytes, baseline.text_bytes)


class PublicTaskSetTests(unittest.TestCase):
    """The shipped task set must load, hash-check and grade its own truth."""

    def test_all_public_tasks_load(self):
        tasks = discover_tasks(TASKS_ROOT)
        ids = {t.id for t in tasks}
        self.assertGreaterEqual(len(ids), 4, ids)
        for expected in ("rolling-token-v1", "rolling-token-v2",
                         "packed-record-v1", "lane-shift-v1"):
            self.assertIn(expected, ids)

    def test_new_tasks_ground_truth_passes(self):
        for task_id in ("packed-record-v1", "lane-shift-v1"):
            task = load_task(TASKS_ROOT / task_id)
            with Grader(task) as grader:
                grade = grader.grade(_ground_truth_source(task))
            self.assertTrue(grade.passed, f"{task_id}: {grade.reason}")
            self.assertGreater(grade.cases_total, 0)


class PrivateTaskTests(unittest.TestCase):
    def _private_copy(self, tmp: str) -> Path:
        copy = Path(tmp) / "task"
        shutil.copytree(BINARY_DIR, copy)
        manifest = json.loads((copy / "task.json").read_text(encoding="utf-8"))
        manifest["private"] = True
        manifest["content_hash"] = ""
        (copy / "task.json").write_text(json.dumps(manifest), encoding="utf-8")
        return copy

    def test_private_task_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._private_copy(tmp)
            with self.assertRaises(TaskError) as ctx:
                load_task(copy, verify_hash=False)
            self.assertIn("private task", str(ctx.exception))
            task = load_task(copy, verify_hash=False, allow_private=True)
            self.assertTrue(task.private)

    def test_private_flag_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._private_copy(tmp)
            manifest = json.loads(
                (copy / "task.json").read_text(encoding="utf-8"))
            manifest["private"] = "yes"
            (copy / "task.json").write_text(json.dumps(manifest),
                                            encoding="utf-8")
            with self.assertRaises(TaskError):
                load_task(copy, verify_hash=False, allow_private=True)


class ArtifactSchemaTests(unittest.TestCase):
    def _copy_task(self, tmp: str) -> Path:
        copy = Path(tmp) / "task"
        shutil.copytree(BINARY_DIR, copy)
        return copy

    def test_artifact_files_are_hashed(self):
        original = load_task(BINARY_DIR).computed_hash()
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy_task(tmp)
            policy = copy / "grader" / "policies" / "level1.json"
            raw = json.loads(policy.read_text(encoding="utf-8"))
            raw["seed"] = 99
            policy.write_text(json.dumps(raw), encoding="utf-8")
            changed = load_task(copy, verify_hash=False).computed_hash()
        self.assertNotEqual(original, changed)

    def test_policy_level_must_match_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy_task(tmp)
            policy = copy / "grader" / "policies" / "level3.json"
            raw = json.loads(policy.read_text(encoding="utf-8"))
            for entry in raw["functions"]:
                entry["level"] = 1
            policy.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(TaskError) as ctx:
                load_task(copy, verify_hash=False)
            self.assertIn("level 3", str(ctx.exception))

    def test_binary_task_requires_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy_task(tmp)
            manifest = json.loads(
                (copy / "task.json").read_text(encoding="utf-8"))
            del manifest["artifact"]
            (copy / "task.json").write_text(json.dumps(manifest),
                                            encoding="utf-8")
            with self.assertRaises(TaskError):
                load_task(copy, verify_hash=False)

    def test_level0_profile_rejects_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy_task(tmp)
            manifest = json.loads(
                (copy / "task.json").read_text(encoding="utf-8"))
            manifest["artifact"]["profiles"]["baseline"]["policy"] = \
                "grader/policies/level1.json"
            (copy / "task.json").write_text(json.dumps(manifest),
                                            encoding="utf-8")
            with self.assertRaises(TaskError):
                load_task(copy, verify_hash=False)


class OracleBrokerTests(unittest.TestCase):
    """The probe must be counted by the harness, not by the adapter."""

    ECHO_PROBE = (
        "import sys\n"
        "data = sys.stdin.buffer.read()\n"
        "sys.stdout.write('n=%d' % len(data))\n"
        "sys.stderr.write('echo')\n")

    def _broker(self, *, budget=None) -> OracleBroker:
        return OracleBroker([sys.executable, "-c", self.ECHO_PROBE],
                            budget=budget)

    def _query(self, broker: OracleBroker, payload: bytes):
        return query(broker.address, payload, transport=broker.transport)

    def test_queries_are_counted_and_capped(self):
        with self._broker(budget=1) as broker:
            code, out, err = self._query(broker, b"abcd")
            self.assertEqual(code, 0)
            self.assertEqual(out, b"n=4")
            self.assertEqual(err, b"echo")
            with self.assertRaises(OracleError) as ctx:
                self._query(broker, b"a")
            self.assertIn("budget exhausted", str(ctx.exception))
        self.assertEqual(broker.stats.queries, 1)
        self.assertEqual(broker.stats.refused, 1)
        self.assertEqual(broker.stats.failed, 0)
        self.assertEqual(broker.stats.enforcement,
                         "enforced by harness broker")

    def test_unset_budget_counts_without_capping(self):
        with self._broker() as broker:
            for _ in range(3):
                self._query(broker, b"x")
        self.assertEqual(broker.stats.queries, 3)
        self.assertEqual(broker.stats.refused, 0)
        self.assertIn("no cap", broker.stats.enforcement)

    def test_workspace_shim_round_trips_and_refuses(self):
        with self._broker(budget=1) as broker, \
                tempfile.TemporaryDirectory() as tmp:
            shim = install_shim(broker, Path(tmp))
            command = ([sys.executable, str(shim)] if os.name == "nt"
                       else [str(shim)])
            first = subprocess.run(command, input=b"hello",
                                   capture_output=True, timeout=30)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(first.stdout, b"n=5")
            self.assertEqual(first.stderr, b"echo")
            second = subprocess.run(command, input=b"hello",
                                    capture_output=True, timeout=30)
            self.assertEqual(second.returncode, 125)
            self.assertIn(b"budget exhausted", second.stderr)
        self.assertEqual(broker.stats.queries, 1)
        self.assertEqual(broker.stats.refused, 1)

    def test_shim_is_a_script_not_a_binary(self):
        with self._broker() as broker, tempfile.TemporaryDirectory() as tmp:
            shim = install_shim(broker, Path(tmp))
            data = shim.read_bytes()
            self.assertTrue(data.startswith(b"#!"))
            self.assertIn(b"harness-owned broker", data)
            self.assertFalse(data.startswith(b"\x7fELF"))


class RunnerOracleTests(unittest.TestCase):
    """Runner integration: shim in the workspace, counts in the run row."""

    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

    def test_queries_reach_the_broker_and_stop_at_the_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.py"
            probe.write_text("import sys\n"
                             "sys.stdout.write('ok')\n", encoding="utf-8")
            task = replace(self.task, budgets=replace(
                self.task.budgets, oracle_queries=2))

            class FakeArtifactRunner(Runner):
                def artifact_for(self, task, profile):
                    return BuiltArtifact(
                        profile=profile, level=0, path=probe,
                        sha256="0" * 64, size_bytes=0, text_bytes=0,
                        toolchain={}, build_log="")

                def _probe_command(self, artifact):
                    return [sys.executable, str(artifact.path)]

            runner = FakeArtifactRunner(repo_root=REPO_ROOT,
                                        out_dir=Path(tmp),
                                        keep_workspaces=True)
            records = runner.run([task], [ProbeQueryAgent(queries=3)],
                                 profile="baseline")
            workspace = next(Path(tmp).glob("ws-*"))
            installed = (workspace / "probe").read_bytes()

        record = records[0]
        self.assertEqual(record.oracle["queries"], 2)
        self.assertEqual(record.oracle["refused"], 1)
        self.assertEqual(record.oracle["budget"], 2)
        self.assertEqual(record.budgets["enforcement"]["oracle_queries"],
                         "enforced by harness broker")
        self.assertTrue(installed.startswith(b"#!"),
                        "the workspace must hold the shim, not the probe")
        self.assertIn(b"Oracle shim", installed)
        self.assertGreater(len(installed), 100)

    def test_reimplementation_tasks_have_no_oracle(self):
        task = load_task(REIMPLEMENT_DIR)
        with tempfile.TemporaryDirectory() as tmp:
            records = Runner(repo_root=REPO_ROOT,
                             out_dir=Path(tmp)).run(
                                 [task], [StubAgent()], profile="baseline")
        self.assertEqual(records[0].oracle, {})
        self.assertEqual(
            records[0].budgets["enforcement"]["oracle_queries"],
            "n/a (no probe)")


class BinaryAccessTests(unittest.TestCase):
    """``access=binary`` ships the probe itself; queries stop being counted.

    Under oracle access the agent's observable world is identical in every
    artifact profile, so a protection transform cannot change its cost. These
    tests pin the mode that can, and the fact that the row says so.
    """

    @classmethod
    def setUpClass(cls):
        cls.task = load_task(BINARY_DIR)

    def _runner(self, tmp: str, **kwargs) -> Runner:
        probe = Path(tmp) / "probe.sh"
        probe.write_text("#!/bin/sh\ncat >/dev/null\necho ok\n",
                         encoding="utf-8", newline="\n")
        probe.chmod(0o755)

        class FakeArtifactRunner(Runner):
            def artifact_for(self, task, profile):
                return BuiltArtifact(
                    profile=profile, level=0, path=probe,
                    sha256="0" * 64, size_bytes=probe.stat().st_size,
                    text_bytes=0, toolchain={}, build_log="")

            def _probe_command(self, artifact):
                return [str(artifact.path)]

        return FakeArtifactRunner(repo_root=REPO_ROOT, out_dir=Path(tmp),
                                  **kwargs)

    def test_probe_is_copied_and_queries_are_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(tmp, keep_workspaces=True, access="binary")
            records = runner.run([self.task], [ProbeQueryAgent(queries=3)],
                                 profile="baseline")
            workspace = next(Path(tmp).glob("ws-*"))
            installed = workspace / "probe"
            payload = installed.read_bytes()
            executable = os.access(installed, os.X_OK)

        record = records[0]
        self.assertEqual(record.access, "binary")
        self.assertEqual(record.oracle["access"], "binary")
        # Not zero: a local binary makes any count the adapter's own claim.
        self.assertIsNone(record.oracle["queries"])
        self.assertEqual(record.budgets["enforcement"]["oracle_queries"],
                         "not counted (binary access)")
        self.assertTrue(payload.startswith(b"#!/bin/sh"),
                        "workspace must hold the probe, not the shim")
        self.assertNotIn(b"Oracle shim", payload)
        self.assertTrue(executable)

    def test_binary_access_refuses_an_oracle_budget(self):
        task = replace(self.task, budgets=replace(
            self.task.budgets, oracle_queries=2))
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp, access="binary").run(
                [task], [StubAgent()], profile="baseline")
        self.assertEqual(records[0].grade.stage, "artifact")
        self.assertIn("cannot be enforced", records[0].error)

    def test_oracle_access_is_recorded_and_still_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run(
                [self.task], [ProbeQueryAgent(queries=2)], profile="baseline")
        self.assertEqual(records[0].access, "oracle")
        self.assertEqual(records[0].oracle["access"], "oracle")
        self.assertEqual(records[0].oracle["queries"], 2)

    def test_markdown_warns_that_oracle_access_cannot_show_a_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp).run(
                [self.task], [ProbeQueryAgent(queries=1)], profile="baseline")
            paths = write_reports(records, Path(tmp))
            markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertIn("structurally zero", markdown)
        self.assertIn("- Access: `oracle`", markdown)

    def test_unknown_access_mode_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                Runner(repo_root=REPO_ROOT, out_dir=Path(tmp), access="syscall")

    def test_markdown_reports_calibration_and_warns_when_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self._runner(tmp, access="binary").run(
                [self.task], [StubAgent()], profile="baseline")
            paths = write_reports(records, Path(tmp))
            markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertIn("- Calibration:", markdown)
        self.assertIn("uncalibrated", markdown)
        self.assertIn("cannot demonstrate a protection effect", markdown)



class BudgetTests(unittest.TestCase):
    def test_oracle_budget_parsing(self):
        self.assertIsNone(Budget.from_dict({}).oracle_queries)
        self.assertEqual(Budget.from_dict({"oracle_queries": 10}).oracle_queries,
                         10)
        self.assertEqual(Budget.from_dict({"oracle_queries": 0}).oracle_queries,
                         0)
        for bad in (-1, True, "10", 1.5):
            with self.assertRaises(TaskError):
                Budget.from_dict({"oracle_queries": bad})


class ReportStatisticsTests(unittest.TestCase):
    def test_wilson_interval_behaves_at_the_edges(self):
        self.assertIsNone(wilson_interval(0, 0))
        low, high = wilson_interval(5, 5)
        self.assertAlmostEqual(low, 0.5655, places=3)
        self.assertEqual(high, 1.0)
        low, high = wilson_interval(0, 5)
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.4345, places=3)
        low, high = wilson_interval(0, 1)
        self.assertEqual(low, 0.0)
        self.assertGreater(high, 0.7)

    def _record(self, profile: str, seconds: float, *,
                passed: bool = True, oracle_queries: int = 5) -> RunRecord:
        grade = Grade(passed, "ok" if passed else "hidden", "ok")
        return RunRecord(
            run_id=f"{profile}-{seconds}", task_id="task-x",
            task_hash="sha256:" + "0" * 64, agent="agent-x",
            adversary="n/a", profile=profile, repetition=0,
            started_utc="2026-11-11T00:00:00Z", duration_seconds=seconds,
            grade=grade,
            ledger={"tokens": 100, "tool_calls": 1,
                    "ledger_source": "self-reported by adapter"},
            budgets={"oracle_queries": None, "enforcement": {}},
            environment={"commit": "abc", "commit_dirty": "no",
                         "platform": "linux", "python": "3.12",
                         "machine": "deadbeef"},
            oracle={"queries": oracle_queries, "refused": 0, "failed": 0,
                    "budget": None, "transport": "unix",
                    "enforcement": "counted by harness broker (no cap)"})

    def test_markdown_reports_intervals_and_cost_delta(self):
        records = [
            self._record("baseline", 1.0),
            self._record("baseline", 2.0),
            self._record("aegis-level1", 3.0),
            self._record("aegis-level1", 4.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            write_markdown(records, path)
            text = path.read_text(encoding="utf-8")
        self.assertIn("pass rate (95% CI)", text)
        self.assertIn("100% [34%-100%]", text)
        self.assertIn("## By (agent, profile), across tasks", text)
        self.assertIn("## Cost delta vs baseline", text)
        self.assertIn("baseline → aegis-level1", text)
        self.assertIn("+2.00", text)
        self.assertIn("self-reported", text)
        self.assertIn("measured by the harness", text)

    def test_single_run_states_no_interval_for_delta(self):
        records = [
            self._record("baseline", 1.0),
            self._record("aegis-level1", 3.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            write_markdown(records, path)
            text = path.read_text(encoding="utf-8")
        self.assertIn("(n<2)", text)


if __name__ == "__main__":
    unittest.main()
