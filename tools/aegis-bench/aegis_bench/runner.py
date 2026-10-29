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

import getpass
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import AdapterError, Agent
from .grader import Grade, Grader
from .schema import Task


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
        "host": platform.node(),
        "user": getpass.getuser(),
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
            "error": self.error,
        }


class Runner:
    def __init__(self, *, repo_root: Path, out_dir: Path,
                 cxx: str | None = None, keep_workspaces: bool = False):
        self.repo_root = Path(repo_root)
        self.out_dir = Path(out_dir)
        self.cxx = cxx
        self.keep_workspaces = keep_workspaces
        self.environment = environment_stamp(self.repo_root)

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
        error = ""
        try:
            self._populate_workspace(task, workspace)
            agent.prepare(task, workspace)
            result = agent.solve(task, workspace)
            ledger = dict(result.ledger)
            ledger["ledger_source"] = "self-reported by adapter"
            if result.notes:
                ledger["notes"] = result.notes
            with Grader(task, cxx=self.cxx) as grader:
                grade = grader.grade(result.sources)
        except AdapterError as exc:
            grade = Grade(False, "agent", f"adapter error: {exc}")
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            grade = Grade(False, "agent", f"adapter crashed: {exc!r}")
            error = traceback.format_exc(limit=5)
        finally:
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
                "max_tool_calls": task.budgets.max_tool_calls,
                "timeout_seconds": task.budgets.timeout_seconds,
                "max_output_tokens": task.budgets.max_output_tokens,
            },
            environment=self.environment, error=error)

    # -- a whole matrix --------------------------------------------------

    def run(self, tasks: list[Task], agents: list[Agent], *, profile: str,
            repetitions: int = 1) -> list[RunRecord]:
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
