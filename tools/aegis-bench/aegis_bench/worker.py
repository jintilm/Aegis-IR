"""Out-of-process adapter worker.

The worker receives a workspace-relative TaskView rather than the repository
task root, imports a fresh adapter, runs one cell, and returns JSON data. On
Linux it can install a Landlock filesystem allowlist and TCP-port restriction;
that is not a full network namespace, so UDP remains outside the boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import AdapterError, Agent, AgentResult, create_agent
from .landlock import LandlockError, apply as apply_landlock
from .schema import Task, TaskError

MAX_RESPONSE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class TaskView:
    """Task metadata safe to hand to an isolated adapter worker."""

    workspace: Path
    id: str
    title: str
    description: str
    interface: str
    candidate_sources: tuple[str, ...]
    visible: tuple[str, ...]
    schema_version: int
    experiment_use: str
    difficulty: str
    tool_policy: dict[str, Any]
    input_domain: dict[str, Any]
    protectability: dict[str, Any]

    @classmethod
    def from_task(cls, task: Task, workspace: Path) -> "TaskView":
        protocol = task.protocol_dict()
        return cls(
            workspace=Path(workspace),
            id=task.id,
            title=task.title,
            description=task.description,
            interface=task.interface,
            candidate_sources=task.candidate_sources,
            visible=task.visible,
            schema_version=task.schema_version,
            experiment_use=task.experiment_use,
            difficulty=task.difficulty,
            tool_policy=protocol["tool_policy"],
            input_domain=protocol["input_domain"],
            protectability=protocol["protectability"],
        )

    @classmethod
    def from_payload(cls, raw: dict[str, Any],
                     workspace: Path) -> "TaskView":
        return cls(
            workspace=Path(workspace),
            id=str(raw["id"]),
            title=str(raw["title"]),
            description=str(raw["description"]),
            interface=str(raw["interface"]),
            candidate_sources=tuple(raw["candidate_sources"]),
            visible=tuple(raw["visible"]),
            schema_version=int(raw["schema_version"]),
            experiment_use=str(raw["experiment_use"]),
            difficulty=str(raw["difficulty"]),
            tool_policy=dict(raw["tool_policy"]),
            input_domain=dict(raw["input_domain"]),
            protectability=dict(raw["protectability"]),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "interface": self.interface,
            "candidate_sources": list(self.candidate_sources),
            "visible": list(self.visible),
            "schema_version": self.schema_version,
            "experiment_use": self.experiment_use,
            "difficulty": self.difficulty,
            "tool_policy": self.tool_policy,
            "input_domain": self.input_domain,
            "protectability": self.protectability,
        }

    def path(self, relative: str) -> Path:
        """Resolve only workspace-visible task paths.

        Ground truth, grader files and hidden cases are deliberately absent
        from the worker's TaskView.
        """
        normal = relative.replace("\\", "/")
        allowed = {self.description, self.interface, *self.visible,
                   *self.candidate_sources}
        visible_dir = any(
            normal == name.rstrip("/")
            or normal.startswith(name.rstrip("/") + "/")
            for name in self.visible)
        if normal not in allowed and not visible_dir:
            raise TaskError(
                f"path is not visible to the adapter worker: {relative}")
        root = self.workspace.resolve()
        candidate = (self.workspace / normal).resolve()
        if candidate != root and root not in candidate.parents:
            raise TaskError(f"path escapes the workspace: {relative}")
        return candidate

    def hidden_paths(self) -> list[Path]:
        return []

    def protocol_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_use": self.experiment_use,
            "difficulty": self.difficulty,
            "tool_policy": self.tool_policy,
            "input_domain": self.input_domain,
            "protectability": self.protectability,
        }


class ProcessIsolatedAgent(Agent):
    """Parent-side proxy that executes one adapter call in a child process."""

    def __init__(self, inner: Agent, *, timeout_seconds: int,
                 tcp_ports: tuple[int, ...] = ()):
        self.name = inner.name
        self.adversary = inner.adversary
        self.version = str(getattr(inner, "version", ""))
        self.adapter_spec = str(
            getattr(inner, "adapter_spec", "") or "")
        if not self.adapter_spec:
            raise AdapterError(
                f"adapter {inner.name} has no importable adapter_spec for "
                f"process isolation")
        self.timeout_seconds = timeout_seconds
        self.tcp_ports = tcp_ports
        self.last_isolation: dict[str, Any] = {
            "adapter": "process",
            "sandbox": False,
            "filesystem": "not restricted",
            "network": "not restricted",
        }

    def _landlock_paths(self) -> list[Path]:
        package_root = Path(__file__).resolve().parents[1]
        repo_root = package_root.parents[1]
        paths = [
            Path("/usr"), Path("/usr/local"), Path("/lib"), Path("/lib64"),
            Path("/bin"), Path("/etc"),
        ]
        candidates = [package_root]
        for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
            if entry:
                candidates.append(Path(entry))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in package_root.parents:
                continue
            if resolved != package_root and repo_root in resolved.parents:
                continue
            paths.append(resolved)
        return paths

    def solve(self, task: Task, workspace: Path) -> AgentResult:
        view = TaskView.from_task(task, workspace)
        request = {
            "adapter_spec": self.adapter_spec,
            "task": view.payload(),
        }
        env = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[1])
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            package_root + (os.pathsep + existing if existing else ""))
        if os.name == "posix" and os.environ.get("AEGIS_LANDLOCK", "1") != "0":
            env["AEGIS_LANDLOCK"] = "1"
            env["AEGIS_LANDLOCK_RO_PATHS"] = os.pathsep.join(
                str(path) for path in self._landlock_paths())
            env["AEGIS_LANDLOCK_TCP_PORTS"] = ",".join(
                str(port) for port in self.tcp_ports)
        with tempfile.TemporaryDirectory(prefix="aegis-worker-") as tmp:
            transport = Path(tmp)
            # Adapter diagnostic saves stay in the per-run transport directory,
            # not a shared /tmp path and not the visible task workspace.
            save_dir = transport / "submissions"
            save_dir.mkdir()
            env["LLM_SAVE_DIR"] = str(save_dir)
            request_path = transport / "request.json"
            response_path = transport / "response.json"
            request_path.write_text(
                json.dumps(request, sort_keys=True) + "\n",
                encoding="utf-8")
            timeout = (None if self.timeout_seconds <= 0
                       else max(1, self.timeout_seconds - 2))
            try:
                proc = subprocess.run(
                    [sys.executable, "-c",
                     "from aegis_bench.worker import main; raise SystemExit(main())",
                     str(request_path), str(response_path),
                     str(workspace)],
                    cwd=workspace, env=env, capture_output=True,
                    timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise AdapterError(
                    f"isolated adapter exceeded {self.timeout_seconds}s") from exc
            if proc.stderr:
                sys.stderr.write(proc.stderr.decode(errors="replace"))
                sys.stderr.flush()
            if not response_path.is_file():
                detail = proc.stdout.decode(errors="replace")[-4000:]
                raise AdapterError(
                    f"isolated adapter exited {proc.returncode} without a "
                    f"result: {detail}")
            if response_path.stat().st_size > MAX_RESPONSE_BYTES:
                raise AdapterError("isolated adapter response is too large")
            try:
                reply = json.loads(response_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise AdapterError(
                    f"cannot read isolated adapter response: {exc}") from exc
        if not reply.get("ok"):
            raise AdapterError(str(reply.get("error") or "adapter failed"))
        isolation = reply.get("isolation")
        if isinstance(isolation, dict):
            self.last_isolation.update(isolation)
        sources = reply.get("sources")
        ledger = reply.get("ledger")
        if not isinstance(sources, dict) or not isinstance(ledger, dict):
            raise AdapterError("isolated adapter returned malformed data")
        return AgentResult(
            sources={str(key): str(value) for key, value in sources.items()},
            ledger=dict(ledger),
            notes=str(reply.get("notes", "")))


def _write_response(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3:
        print("usage: python -m aegis_bench.worker REQUEST RESPONSE WORKSPACE",
              file=sys.stderr)
        return 2
    request_path, response_path, workspace_raw = map(Path, argv)
    workspace = workspace_raw.resolve()
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        task = TaskView.from_payload(request["task"], workspace)
        isolation = {
            "adapter": "process",
            "sandbox": False,
            "filesystem": "not restricted",
            "network": "not restricted",
        }
        if os.environ.get("AEGIS_LANDLOCK") == "1":
            try:
                ro_paths = [
                    Path(value) for value in
                    os.environ.get("AEGIS_LANDLOCK_RO_PATHS", "").split(
                        os.pathsep) if value
                ]
                ports = [
                    int(value) for value in
                    os.environ.get("AEGIS_LANDLOCK_TCP_PORTS", "").split(
                        ",") if value
                ]
                metadata = apply_landlock(
                    rw_paths=[workspace, request_path.parent],
                    ro_paths=ro_paths,
                    tcp_ports=ports)
                isolation.update(metadata)
                isolation["sandbox"] = True
            except (LandlockError, OSError, ValueError) as exc:
                _write_response(response_path, {
                    "ok": False,
                    "error": f"cannot install worker sandbox: {exc}",
                })
                return 0
        agent = create_agent(str(request["adapter_spec"]))
        agent.prepare(task, workspace)
        result = agent.solve(task, workspace)
        _write_response(response_path, {
            "ok": True,
            "sources": result.sources,
            "ledger": result.ledger,
            "notes": result.notes,
            "isolation": isolation,
        })
        return 0
    except AdapterError as exc:
        _write_response(response_path, {"ok": False, "error": str(exc)})
        return 0
    except BaseException as exc:
        _write_response(response_path, {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        })
        return 0


if __name__ == "__main__":
    sys.exit(main())
