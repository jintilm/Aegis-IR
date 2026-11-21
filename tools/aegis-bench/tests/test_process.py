"""Offline subprocess boundary regressions; no compiler or model required."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aegis_bench.process import OutputLimitExceeded, ProcessCancelled, run_bounded
from aegis_bench.grader import Grader


class BoundedProcessTests(unittest.TestCase):
    def run_python(self, code, **kwargs):
        options = dict(timeout=5, max_stdout_bytes=1024, max_stderr_bytes=1024)
        options.update(kwargs)
        return run_bounded([sys.executable, "-c", code], **options)

    def test_exact_boundary_and_stdin_round_trip(self):
        result = self.run_python(
            "import sys; data=sys.stdin.buffer.read(); "
            "sys.stdout.buffer.write(data); sys.stderr.buffer.write(data)",
            input=b"a" * 1024)
        self.assertEqual(result.stdout, b"a" * 1024)
        self.assertEqual(result.stderr, b"a" * 1024)
        self.assertEqual(result.returncode, 0)

    def test_stdout_and_stderr_overflow_are_failures(self):
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), self.assertRaises(
                    OutputLimitExceeded) as caught:
                self.run_python(
                    f"import sys; sys.{stream}.buffer.write(b'x' * 1025)")
            self.assertEqual(caught.exception.stream, stream)
            self.assertEqual(len(getattr(caught.exception, stream)), 1024)

    def test_output_before_reading_large_stdin_does_not_deadlock(self):
        result = self.run_python(
            "import sys; sys.stdout.buffer.write(b'x' * 262144); "
            "sys.stdout.flush(); data=sys.stdin.buffer.read(); "
            "sys.stderr.write(str(len(data)))",
            input=b"a" * 262144, max_stdout_bytes=262144)
        self.assertEqual(result.stderr, b"262144")

    def test_timeout_kills_child(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_python("import time; time.sleep(10)", timeout=0.2)

    def test_service_can_cancel_a_running_child(self):
        cancel = threading.Event()
        timer = threading.Timer(0.2, cancel.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(ProcessCancelled):
                self.run_python("import time; time.sleep(10)",
                                cancel_event=cancel)
        finally:
            timer.cancel()
            timer.join()
        self.assertLess(time.monotonic() - started, 2)

    @unittest.skipUnless(os.name == "posix", "POSIX nonblocking pipe cleanup")
    def test_detached_pipe_owner_does_not_leak_capture_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            code = (
                "import subprocess,sys; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(10)'], start_new_session=True); "
                f"Path({str(pid_file)!r}).write_text(str(child.pid))")
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.run_python(code, timeout=0.5)
                readers = [thread for thread in threading.enumerate()
                           if thread.name.startswith("aegis-capture-")]
                self.assertEqual(readers, [])
            finally:
                if pid_file.is_file():
                    try:
                        os.kill(int(pid_file.read_text()), 9)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(os.name == "posix", "POSIX process group cleanup")
    def test_timeout_kills_descendant_holding_output_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "descendant-finished"
            child = (
                "import time; from pathlib import Path; time.sleep(1); "
                f"Path({str(marker)!r}).write_text('unexpected')")
            code = (
                "import subprocess,sys; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}])")
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_python(code, timeout=0.2)
            time.sleep(1)
            self.assertFalse(marker.exists())


class GraderOutputTests(unittest.TestCase):
    def test_candidate_overflow_is_a_failed_case(self):
        with Grader(None) as grader:
            with mock.patch.object(grader, "reference", return_value=(Path("ref"), "")), \
                    mock.patch.object(grader, "_build_candidate", return_value=(Path("cand"), "")), \
                    mock.patch.object(grader, "_corpus", return_value=[("hidden:case", b"")]), \
                    mock.patch.object(grader, "_run", side_effect=[
                        (b"prefix", 0, ""),
                        OutputLimitExceeded("stdout", 6, b"prefix", b"")]):
                grade = grader.grade({})
        self.assertFalse(grade.passed)
        self.assertEqual(grade.cases_passed, 0)
        self.assertIn("output exceeds", grade.failures[0].detail)

    @unittest.skipUnless(os.name == "posix", "executable fixture uses a shebang")
    def test_grader_run_enforces_stdout_and_stderr_limits(self):
        with Grader(None) as grader:
            for stream in ("stdout", "stderr"):
                executable = grader.workdir / "emit"
                executable.write_text(
                    f"#!{sys.executable}\nimport sys\n"
                    f"sys.{stream}.buffer.write(b'x' * (1024 * 1024 + 1))\n")
                executable.chmod(0o755)
                with self.subTest(stream=stream), self.assertRaises(OutputLimitExceeded):
                    grader._run(executable, b"")


if __name__ == "__main__":
    unittest.main()
