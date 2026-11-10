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
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.adapters.fake import BrokenAgent, ReplayAgent, StubAgent  # noqa: E402
from aegis_bench.artifact import ArtifactError  # noqa: E402
from aegis_bench.grader import Grader  # noqa: E402
from aegis_bench.report import write_reports  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import TaskError, discover_tasks, load_task  # noqa: E402

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
            for key in ("task_hash", "profile", "agent", "environment",
                        "budgets", "grade", "artifact"):
                self.assertIn(key, row)
            self.assertEqual(row["task_hash"], self.task.content_hash)
            self.assertIn("commit", row["environment"])
            self.assertEqual(row["artifact"]["level"], 0)
            self.assertEqual(len(row["artifact"]["sha256"]), 64)
            self.assertGreater(row["artifact"]["text_bytes"], 0)
            markdown = paths["markdown"].read_text(encoding="utf-8")
            self.assertIn("self-reported by the adapter", markdown)

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


if __name__ == "__main__":
    unittest.main()
