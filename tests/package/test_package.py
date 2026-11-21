"""Offline checks for the release build/test boundary; no LLVM is needed."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"),
                     "release packaging runs under Bash on Linux")
class PackageBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aegis-package-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source with spaces"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "build").mkdir()
        shutil.copyfile(REPO_ROOT / "scripts" / "package-build.sh",
                        self.root / "scripts" / "package-build.sh")
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.marker = self.root / "ctest-invoked"
        self.log = self.root / "build" / "package-ctest.log"
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "AEGIS_PACKAGE_SKIP_TESTS": "0"}
        self.env.pop("REPO_ROOT", None)
        self._stub("cmake", """#!/usr/bin/env bash
set -eu
test "$PWD" = "$PACKAGE_EXPECTED_ROOT"
exit 0
""")
        self._stub("ctest", """#!/usr/bin/env bash
set -eu
test "$PWD" = "$PACKAGE_EXPECTED_ROOT"
test "$1" = --test-dir
test "$2" = "$PACKAGE_EXPECTED_ROOT/build"
test "$3" = --output-on-failure
printf 'invoked\\n' > "$PACKAGE_EXPECTED_ROOT/ctest-invoked"
printf 'CTest diagnostic output\\n'
exit "${PACKAGE_CTEST_STATUS:-0}"
""")
        self.env["PACKAGE_EXPECTED_ROOT"] = str(self.root)

    def _stub(self, name: str, text: str) -> None:
        path = self.bin / name
        path.write_text(text, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def _run(self) -> subprocess.CompletedProcess:
        # The caller's cwd is intentionally not the source tree.
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "package-build.sh")],
            cwd=self.temp.name, env=self.env, capture_output=True, text=True,
            timeout=15)

    def test_success_requires_ctest_and_uses_source_directory(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.is_file())
        self.assertIn("CTest diagnostic output", self.log.read_text())
        self.assertIn("build + tests OK", result.stdout)

    def test_ctest_failure_propagates_and_keeps_diagnostic(self) -> None:
        self.env["PACKAGE_CTEST_STATUS"] = "7"
        result = self._run()
        self.assertEqual(result.returncode, 7)
        self.assertTrue(self.marker.is_file())
        self.assertIn("CTest diagnostic output", result.stdout)
        self.assertNotIn("build + tests OK", result.stdout)

    def test_unwritable_log_fails_before_ctest(self) -> None:
        # A directory cannot be opened as a log, even when CI runs as root.
        self.log.mkdir()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())
        self.assertIn("package-ctest.log", result.stderr)
        self.assertNotIn("build + tests OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
