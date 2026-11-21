"""Cached and per-run probes must match their recorded provenance."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
REPO_ROOT = TOOL_ROOT.parents[1]
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.artifact import (  # noqa: E402
    CACHE_VERSION, ArtifactBuilder, ArtifactError)
from aegis_bench.schema import load_task  # noqa: E402


class ArtifactIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_task(
            REPO_ROOT / "benchmarks/tasks-public/rolling-token-v2")

    def _cache(self, root: Path):
        builder = ArtifactBuilder(cache_root=root)
        builder._toolchain = {"clang": "fixture-clang", "opt": "fixture-opt"}
        builder._fingerprint = "fixture"
        digest = self.task.content_hash.split(":", 1)[-1][:16]
        directory = (root / self.task.id /
                     f"{CACHE_VERSION}-baseline-{digest}-fixture")
        directory.mkdir(parents=True)
        probe = directory / ("probe.exe" if os.name == "nt" else "probe")
        data = b"original cached artifact"
        probe.write_bytes(data)
        metadata = {
            "profile": "baseline", "level": 0,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data), "text_bytes": 0,
            "toolchain": builder._toolchain, "build_log": "fixture",
        }
        meta_path = directory / "artifact.json"
        meta_path.write_text(json.dumps(metadata), encoding="utf-8")
        return builder, probe, meta_path

    def test_valid_disk_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder, probe, _ = self._cache(Path(tmp))
            built = builder.build(self.task, "baseline")
            self.assertEqual(built.path, probe)
            self.assertEqual(built.verified_bytes(), probe.read_bytes())

    def test_corrupted_disk_cache_is_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder, probe, _ = self._cache(Path(tmp))
            probe.write_bytes(b"x" * probe.stat().st_size)
            with self.assertRaisesRegex(ArtifactError, "SHA-256"):
                builder.build(self.task, "baseline")

    def test_memory_cache_is_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder, probe, _ = self._cache(Path(tmp))
            builder.build(self.task, "baseline")
            probe.write_bytes(b"short")
            with self.assertRaisesRegex(ArtifactError, "size"):
                builder.build(self.task, "baseline")

    def test_inconsistent_or_malformed_cache_metadata_is_rejected(self):
        for field, value in (("profile", "aegis-level3"), ("level", 3),
                             ("toolchain", {"clang": "different"})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                builder, _, path = self._cache(Path(tmp))
                metadata = json.loads(path.read_text(encoding="utf-8"))
                metadata[field] = value
                path.write_text(json.dumps(metadata), encoding="utf-8")
                with self.assertRaisesRegex(ArtifactError, "metadata"):
                    builder.build(self.task, "baseline")
        with tempfile.TemporaryDirectory() as tmp:
            builder, _, path = self._cache(Path(tmp))
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ArtifactError, "metadata"):
                builder.build(self.task, "baseline")

    def test_snapshot_survives_cache_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder, probe, _ = self._cache(root / "cache")
            artifact = builder.build(self.task, "baseline")
            private = root / "private"
            private.mkdir()
            frozen = artifact.snapshot(private)
            probe.write_bytes(b"replacement")
            self.assertEqual(frozen.verified_bytes(), b"original cached artifact")
            self.assertEqual(frozen.sha256, artifact.sha256)
            if os.name == "posix":
                self.assertEqual(frozen.path.stat().st_mode & 0o222, 0)


if __name__ == "__main__":
    unittest.main()
