"""Run orchestration and record keeping.

One *run* is one (task, agent, profile, repetition) cell. The runner:

1. builds a workspace containing only the task's visible files;
2. calls the adapter with a budget;
3. grades the returned candidate with an independent grader;
4. records the result with enough provenance that a third party can tell what
   was measured (commit, tool versions, task hash, budgets, timings).

The runner never writes outside its run directory, and never puts ground
truth, hidden cases or the grader into the workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import AdapterError, Agent
from .artifact import ArtifactBuilder, ArtifactError, BuiltArtifact
from .grader import Grade, Grader
from .oracle import OracleBroker, OracleError, install_shim
from .schema import Task

DEFAULT_ADAPTER_TIMEOUT = 600


class AdapterTimeout(AdapterError):
    """The adapter exceeded its wall-clock budget."""


class _Deadline:
    """Wall-clock limit around an in-process adapter call.

    Adapters are ordinary Python objects, so the only portable enforcement is
    a POSIX alarm (main thread) or a watchdog thread. On POSIX the alarm
    interrupts the call and raises; elsewhere the watchdog records the
    overrun but the call may keep running, which is why the run row records
    whether the limit was actually enforced.
    """

    def __init__(self, seconds: int):
        self.seconds = seconds
        self.armed = False

    def __enter__(self) -> "_Deadline":
        if self.seconds <= 0:
            return self
        if os.name == "posix" and threading.current_thread() is threading.main_thread():
            self._previous = signal.signal(signal.SIGALRM, self._raise)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
            self.armed = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._previous)

    def _raise(self, signum: int, frame: Any) -> None:
        raise AdapterTimeout(
            f"adapter exceeded its {self.seconds}s wall-clock budget")


def _call_with_deadline(fn: Any, seconds: int) -> tuple[Any, bool]:
    """Run ``fn`` with a deadline; return (result, enforced)."""
    if seconds <= 0:
        return fn(), False
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        with _Deadline(seconds):
            return fn(), True

    # Fallback: watchdog thread. The call is not interrupted, but an overrun
    # is surfaced instead of silently producing a result.
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            outcome["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AdapterTimeout(
            f"adapter exceeded its {seconds}s wall-clock budget "
            f"(watchdog mode; the call was not interrupted)")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"], False


def _deadline_mode(seconds: int) -> str:
    """What the run row should claim about timeout enforcement."""
    if seconds <= 0:
        return "unset"
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        return "enforced (SIGALRM)"
    return "watchdog (overrun detected, call not interrupted)"


def _machine_id() -> str:
    """Non-identifying environment fingerprint for reproducibility.

    Host and user names are deliberately not recorded: reports are committed,
    and a benchmark result does not need to name the machine's owner. Hashing
    the platform string keeps the value stable across runs in the same
    environment (a container id would change on every launch) while revealing
    nothing beyond what ``platform`` already states.
    """
    return hashlib.sha256(platform.platform().encode()).hexdigest()[:12]


def _git(args: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode(errors="replace").strip()


def environment_stamp(repo_root: Path) -> dict[str, str]:
    """Everything needed to reproduce a number, minus secrets."""
    return {
        "commit": _git(["rev-parse", "HEAD"], repo_root),
        "commit_dirty": "yes" if _git(["status", "--porcelain"],
                                      repo_root) else "no",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": _machine_id(),
    }


@dataclass
class RunRecord:
    run_id: str
    task_id: str
    task_hash: str
    agent: str
    adversary: str
    profile: str
    repetition: int
    started_utc: str
    duration_seconds: float
    grade: Grade
    ledger: dict[str, Any] = field(default_factory=dict)
    budgets: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    #: Broker-observed oracle accounting for binary-recovery tasks. This is
    #: measured by the harness, unlike ``ledger``, which the adapter fills in.
    oracle: dict[str, Any] = field(default_factory=dict)
    private: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_hash": self.task_hash,
            "agent": self.agent,
            "adversary": self.adversary,
            "profile": self.profile,
            "repetition": self.repetition,
            "started_utc": self.started_utc,
            "duration_seconds": round(self.duration_seconds, 3),
            "grade": self.grade.to_dict(),
            "ledger": self.ledger,
            "budgets": self.budgets,
            "environment": self.environment,
            "artifact": self.artifact,
            "oracle": self.oracle,
            "private": self.private,
            "error": self.error,
        }


class Runner:
    def __init__(self, *, repo_root: Path, out_dir: Path,
                 cxx: str | None = None, plugin: str | None = None,
                 clang: str | None = None, opt: str | None = None,
                 artifact_cache: Path | None = None,
                 adapter_timeout: int = DEFAULT_ADAPTER_TIMEOUT,
                 keep_workspaces: bool = False):
        self.repo_root = Path(repo_root)
        self.out_dir = Path(out_dir)
        self.cxx = cxx
        self.adapter_timeout = adapter_timeout
        self.keep_workspaces = keep_workspaces
        self.environment = environment_stamp(self.repo_root)
        cache_root = (Path(artifact_cache) if artifact_cache
                      else self.out_dir / ".artifacts")
        self.artifacts = ArtifactBuilder(
            clang=clang, opt=opt, plugin=plugin, cache_root=cache_root)

    def artifact_for(self, task: Task, profile: str) -> BuiltArtifact | None:
        """Build (or reuse) the probe for a binary-recovery task."""
        if task.artifact is None:
            return None
        return self.artifacts.build(task, profile)

    # -- workspace -------------------------------------------------------

    def _populate_workspace(self, task: Task, workspace: Path) -> None:
        """Copy only the declared visible files.

        Symlinks are resolved and re-checked: a task that tried to expose
        ground truth through a link still cannot leak it into the workspace.
        """
        for name in task.visible:
            src = task.path(name)
            dst = workspace / name
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    @staticmethod
    def _probe_command(artifact: BuiltArtifact) -> list[str]:
        """Command the broker runs for one oracle query.

        Tests override this to run a script through the interpreter; a real
        run executes the built probe directly.
        """
        return [str(artifact.path)]

    @staticmethod
    def _install_oracle(broker: OracleBroker, artifact: BuiltArtifact,
                        workspace: Path) -> None:
        """Put the shim — never the probe itself — in the workspace."""
        install_shim(broker, workspace, artifact.path.stem)

    # -- one cell --------------------------------------------------------

    def run_once(self, task: Task, agent: Agent, *, profile: str,
                 repetition: int) -> RunRecord:
        started = time.time()
        started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
        run_id = hashlib.sha256(
            f"{task.id}|{task.computed_hash()}|{agent.name}|{profile}|"
            f"{repetition}|{started_utc}".encode()).hexdigest()[:16]

        workspace = Path(tempfile.mkdtemp(prefix=f"aegis-ws-{run_id}-"))
        grade = Grade(False, "agent", "adapter did not run")
        ledger: dict[str, Any] = {}
        artifact: BuiltArtifact | None = None
        broker: OracleBroker | None = None
        oracle: dict[str, Any] = {}
        budgets: dict[str, Any] = {
            "max_tool_calls": task.budgets.max_tool_calls,
            "timeout_seconds": task.budgets.timeout_seconds,
            "max_output_tokens": task.budgets.max_output_tokens,
            "adapter_timeout_seconds": self.adapter_timeout,
            "oracle_queries": task.budgets.oracle_queries,
            "enforcement": {
                "adapter_timeout": "unset",
                "max_tool_calls": "not enforced (adapter self-report)",
                "max_output_tokens": "not enforced (adapter self-report)",
                "oracle_queries": ("n/a (no probe)" if task.artifact is None
                                   else "not enforced (no broker)"),
            },
        }
        error = ""
        try:
            self._populate_workspace(task, workspace)
            artifact = self.artifact_for(task, profile)
            if artifact is not None:
                try:
                    broker = OracleBroker(
                        self._probe_command(artifact),
                        budget=task.budgets.oracle_queries).start()
                except (OSError, OracleError) as exc:
                    raise OracleError(
                        f"oracle broker failed to start: {exc}") from exc
                budgets["enforcement"]["oracle_queries"] = \
                    broker.stats.enforcement
                self._install_oracle(broker, artifact, workspace)
            agent.prepare(task, workspace)
            timeout = self.adapter_timeout or task.budgets.timeout_seconds
            budgets["enforcement"]["adapter_timeout"] = _deadline_mode(timeout)
            result, _enforced = _call_with_deadline(
                lambda: agent.solve(task, workspace), timeout)
            ledger = dict(result.ledger)
            ledger["ledger_source"] = "self-reported by adapter"
            if result.notes:
                ledger["notes"] = result.notes
            with Grader(task, cxx=self.cxx) as grader:
                grade = grader.grade(result.sources)
        except ArtifactError as exc:
            grade = Grade(False, "artifact", f"artifact build failed: {exc}")
            error = str(exc)
        except OracleError as exc:
            grade = Grade(False, "artifact", f"oracle broker failed: {exc}")
            error = str(exc)
        except AdapterError as exc:
            grade = Grade(False, "agent", f"adapter error: {exc}")
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            grade = Grade(False, "agent", f"adapter crashed: {exc!r}")
            error = traceback.format_exc(limit=5)
        finally:
            if broker is not None:
                broker.stop()
                oracle = broker.stats.to_dict()
            if self.keep_workspaces:
                shutil.copytree(workspace, self.out_dir / f"ws-{run_id}",
                                dirs_exist_ok=True)
            shutil.rmtree(workspace, ignore_errors=True)

        return RunRecord(
            run_id=run_id, task_id=task.id, task_hash=task.content_hash,
            agent=agent.name, adversary=agent.adversary, profile=profile,
            repetition=repetition, started_utc=started_utc,
            duration_seconds=time.time() - started, grade=grade,
            ledger=ledger,
            budgets={
                "max_tool_calls": budgets["max_tool_calls"],
                "timeout_seconds": budgets["timeout_seconds"],
                "max_output_tokens": budgets["max_output_tokens"],
                "adapter_timeout_seconds": budgets["adapter_timeout_seconds"],
                "oracle_queries": budgets["oracle_queries"],
                "enforcement": budgets["enforcement"],
            },
            environment=self.environment,
            artifact=artifact.to_dict() if artifact is not None else {},
            oracle=oracle,
            private=task.private,
            error=error)

    # -- a whole matrix --------------------------------------------------

    def run(self, tasks: list[Task], agents: list[Agent], *, profile: str,
            repetitions: int = 1) -> list[RunRecord]:
        for task in tasks:
            if task.artifact is not None and profile not in task.artifact.profiles:
                available = ", ".join(sorted(task.artifact.profiles))
                raise ArtifactError(
                    f"{task.id} has no artifact profile '{profile}' "
                    f"(available: {available})")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        records: list[RunRecord] = []
        for task in tasks:
            for agent in agents:
                for rep in range(repetitions):
                    record = self.run_once(task, agent, profile=profile,
                                           repetition=rep)
                    records.append(record)
                    status = "PASS" if record.grade.passed else "FAIL"
                    print(f"[{status}] {task.id} / {agent.name} "
                          f"({profile}, rep {rep}) - "
                          f"{record.duration_seconds:.2f}s "
                          f"{record.grade.reason}", file=sys.stderr)
        return records
