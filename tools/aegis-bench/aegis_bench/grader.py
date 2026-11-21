"""Independent grader.

The grader is the only component that touches ground truth. It works by
execution, not inspection:

1. build the *reference* binary from the task's ground-truth source + the
   task's own ``driver.cpp``/``properties.cpp``;
2. build the *candidate* binary from the adapter's sources + the same driver
   and property tests;
3. run both over the hidden cases and a seeded fuzz corpus, comparing stdout
   bytes and exit codes.

Nothing an adapter returns is executed directly: candidate text is written to
a fresh directory, compiled from scratch, and treated as hostile input. The
grader never reads the adapter's notes or ledger when deciding a score.

Isolation in this version is process-level, not a sandbox:

* the include path never contains the task root, so a candidate cannot include
  the ground truth through the compiler's search path (policy.py rejects
  absolute and parent-relative includes as a second line);
* compilation and every run happen in a private scratch directory with a
  minimal environment;
* each run is bounded by a wall-clock timeout, an address-space rlimit and an
  output-size cap.

A malicious candidate that opens sockets or walks the filesystem is not
contained by this. Real runs must put the adapter and grader in a container or
namespace; `docs/benchmark-protocol.md` says so explicitly.

Scores are intentionally coarse. A candidate that agrees on every case is
``passed``; anything else is ``failed`` with a machine-readable reason, so a
report can break failures down by cause instead of collapsing them into one
number.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .policy import check_candidate
from .process import OutputLimitExceeded, run_bounded
from .schema import Task

COMPILE_TIMEOUT = 120
RUN_TIMEOUT = 10
MAX_STDERR_CHARS = 2000
MAX_STDOUT_BYTES = 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
RUN_ADDRESS_SPACE_BYTES = 1024 * 1024 * 1024


def _minimal_env() -> dict[str, str]:
    """Environment for compiling and running untrusted candidate code."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "LC_ALL": "C", "LANG": "C"}
    for key in ("TMPDIR", "SYSTEMROOT", "WINDIR"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _limit_resources() -> None:  # pragma: no cover - runs in the child
    """Best-effort rlimits; silently skipped where unsupported."""
    try:
        import resource
    except ImportError:  # Windows
        return
    for limit, value in ((resource.RLIMIT_AS, RUN_ADDRESS_SPACE_BYTES),
                         (resource.RLIMIT_CORE, 0),
                         (resource.RLIMIT_FSIZE, 16 * 1024 * 1024)):
        try:
            soft, hard = resource.getrlimit(limit)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass


def _load_hidden_cases(path: Path) -> list[tuple[str, bytes]]:
    """Read one hidden-case file.

    Two shapes are supported: a raw binary blob (one case per file), or a
    JSON document ``{"cases": ["<hex>", ...]}`` for cases that are easier to
    review and diff as text. Hex is used rather than base64 because a hex
    corpus diffs cleanly in review.
    """
    if path.suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw.get("cases") if isinstance(raw, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{path}: expected {{\"cases\": [hex, ...]}}")
        return [(f"hidden:{path.stem}#{i}", bytes.fromhex(entry))
                for i, entry in enumerate(entries)]
    return [(f"hidden:{path.name}", path.read_bytes())]


@dataclass
class CaseOutcome:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Grade:
    passed: bool
    stage: str                      # build | artifact | hidden | fuzz | ok
    reason: str = ""
    cases_total: int = 0
    cases_passed: int = 0
    failures: list[CaseOutcome] = field(default_factory=list)
    stderr_excerpt: str = ""

    @property
    def success_rate(self) -> float:
        if self.cases_total == 0:
            return 1.0 if self.passed else 0.0
        return self.cases_passed / self.cases_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "stage": self.stage,
            "reason": self.reason,
            "cases_total": self.cases_total,
            "cases_passed": self.cases_passed,
            "success_rate": round(self.success_rate, 6),
            "failures": [
                {"case": f.name, "detail": f.detail} for f in self.failures[:20]
            ],
            "stderr_excerpt": self.stderr_excerpt,
        }


class Grader:
    def __init__(self, task: Task, *, cxx: str | None = None,
                 workdir: Path | None = None):
        self.task = task
        self.cxx = cxx or os.environ.get("BENCH_CXX", "c++")
        self._own_workdir = workdir is None
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="aegis-grade-"))
        self._reference: Path | None = None

    # -- lifecycle -------------------------------------------------------

    def __enter__(self) -> "Grader":
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._own_workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)

    # -- building --------------------------------------------------------

    def _compile(self, name: str, sources: list[Path],
                 include_dirs: list[Path]) -> tuple[Path | None, str]:
        # Windows needs the extension on the output path or the compiler
        # writes ``name.exe`` while the harness looks for ``name``.
        out = self.workdir / "bin" / (name + (".exe" if os.name == "nt" else ""))
        out.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.workdir / f"cwd-{name}"
        scratch.mkdir(parents=True, exist_ok=True)
        cmd = [self.cxx, "-std=c++17", "-O1", "-g0", *map(str, sources)]
        for inc in include_dirs:
            cmd += ["-I", str(inc)]
        cmd += ["-o", str(out)]
        try:
            proc = run_bounded(
                cmd, cwd=scratch, env=_minimal_env(), timeout=COMPILE_TIMEOUT,
                max_stdout_bytes=MAX_STDOUT_BYTES,
                max_stderr_bytes=MAX_STDERR_BYTES)
        except (OSError, subprocess.TimeoutExpired, OutputLimitExceeded) as exc:
            return None, f"compiler invocation failed: {exc}"
        if proc.returncode != 0:
            return None, proc.stderr.decode(errors="replace")[:MAX_STDERR_CHARS]
        return out, ""

    def _common_sources(self) -> tuple[list[Path], list[Path]]:
        driver = self.task.path(self.task.driver)
        props = self.task.path(self.task.properties)
        include = self.task.path(self.task.interface).parent
        # The driver and property tests are grader-owned headers/sources, so
        # their directories are on the include path. The task root is
        # deliberately absent: with it, a candidate could `#include
        # "ground_truth/target.cpp"` and skip the task entirely.
        includes = [include, driver.parent, props.parent]
        return [driver, props], includes

    def reference(self) -> tuple[Path | None, str]:
        """Build (and cache) the ground-truth binary."""
        if self._reference is not None:
            return self._reference, ""
        common, includes = self._common_sources()
        truth = self.task.path(self.task.ground_truth)
        exe, err = self._compile("reference", [*common, truth], includes)
        self._reference = exe
        return exe, err

    def _build_candidate(self, sources: dict[str, str]
                         ) -> tuple[Path | None, str]:
        """Materialise candidate sources into a scratch dir and compile them.

        Adapter-provided names are sanitised to bare filenames; a source with
        a path separator, a traversal segment, or an unexpected extension is
        rejected rather than written anywhere.
        """
        candidate_dir = self.workdir / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        allowed = set(self.task.candidate_sources)
        written: list[Path] = []
        for name, text in sources.items():
            if name not in allowed:
                return None, (f"adapter returned unexpected source '{name}'; "
                              f"expected one of {sorted(allowed)}")
            if not isinstance(text, str):
                return None, f"source '{name}' is not text"
        missing = allowed - set(sources)
        if missing:
            return None, f"adapter omitted required source(s): {sorted(missing)}"

        # Reject oracle replay / grader-material access before touching disk.
        rejection = check_candidate(
            sources,
            allowed_headers=(self.task.path(self.task.interface).name,))
        if rejection:
            return None, f"candidate rejected by policy: {rejection}"

        for name, text in sources.items():
            path = candidate_dir / name
            path.write_text(text, encoding="utf-8")
            written.append(path)
        common, includes = self._common_sources()
        return self._compile("candidate", [*common, *written],
                             [*includes, candidate_dir])

    # -- executing -------------------------------------------------------

    def _run(self, exe: Path, payload: bytes) -> tuple[bytes, int, str]:
        # Private working directory + minimal environment: a candidate cannot
        # find task files relative to cwd and cannot read credentials from the
        # harness environment. rlimits bound memory, core dumps and file
        # output; they are best-effort on platforms without `resource`.
        with tempfile.TemporaryDirectory(prefix="aegis-run-") as cwd:
            proc = run_bounded(
                [str(exe)], input=payload,
                timeout=RUN_TIMEOUT, cwd=cwd, env=_minimal_env(),
                max_stdout_bytes=MAX_STDOUT_BYTES,
                max_stderr_bytes=MAX_STDERR_BYTES,
                preexec_fn=_limit_resources if os.name == "posix" else None)
        return proc.stdout, proc.returncode, proc.stderr.decode(errors="replace")

    def _corpus(self) -> list[tuple[str, bytes]]:
        cases: list[tuple[str, bytes]] = []
        for path in self.task.hidden_paths():
            cases.extend(_load_hidden_cases(path))
        fuzz = self.task.fuzz
        rnd = random.Random(fuzz.seed)
        for i in range(fuzz.cases):
            length = rnd.randrange(0, fuzz.max_len + 1)
            payload = bytes(rnd.randrange(256) for _ in range(length))
            cases.append((f"fuzz:{i}", payload))
        return cases

    def grade(self, sources: dict[str, str]) -> Grade:
        ref, err = self.reference()
        if ref is None:
            return Grade(False, "build", f"reference build failed: {err}",
                         stderr_excerpt=err)

        cand, err = self._build_candidate(sources)
        if cand is None:
            return Grade(False, "build", f"candidate build failed: {err}",
                         stderr_excerpt=err)

        cases = self._corpus()
        passed = 0
        failures: list[CaseOutcome] = []
        for name, payload in cases:
            try:
                ref_out, ref_code, _ = self._run(ref, payload)
            except subprocess.TimeoutExpired:
                return Grade(False, "hidden",
                             f"reference timed out on {name}")
            except OutputLimitExceeded as exc:
                return Grade(False, "hidden", f"reference {exc} on {name}")
            try:
                out, code, stderr = self._run(cand, payload)
            except subprocess.TimeoutExpired:
                failures.append(CaseOutcome(name, False, "timeout"))
                continue
            except OutputLimitExceeded as exc:
                failures.append(CaseOutcome(name, False, str(exc)))
                continue
            if "PROPERTY FAIL" in stderr:
                detail = next(line for line in stderr.splitlines()
                              if "PROPERTY FAIL" in line)
                failures.append(CaseOutcome(name, False, detail.strip()))
            elif (out, code) != (ref_out, ref_code):
                failures.append(CaseOutcome(
                    name, False,
                    f"output/exit mismatch (ref exit {ref_code}, "
                    f"candidate exit {code})"))
            else:
                passed += 1

        ok = passed == len(cases)
        stage = "ok" if ok else (
            "hidden" if any(f.name.startswith("hidden:") for f in failures)
            else "fuzz")
        reason = "" if ok else f"{len(failures)}/{len(cases)} case(s) failed"
        return Grade(ok, stage, reason, len(cases), passed, failures)
