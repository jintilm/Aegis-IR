"""Out-of-process adapter worker.

The worker receives a workspace-relative TaskView rather than the repository
task root, imports a fresh adapter, runs one cell, and returns JSON data. On
Linux it can install Landlock/seccomp and enter a private network namespace
whose broker/meter traffic is bridged over Unix sockets.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import AdapterError, Agent, AgentResult, create_agent
from .container import (
    ContainerConfig, ContainerError, adapter_mounts_from_env, build_command,
    container_env)
from .landlock import LandlockError, apply as apply_landlock
from .netns import (
    LoopbackBridge, NetnsError, bring_up_loopback, namespace_inode,
    unshare_options)
from .schema import Task, TaskError
from .seccomp import SeccompError, apply_socket_policy

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
NETNS_ENV = "AEGIS_NETWORK_NAMESPACE"
METER_UNIX_ENV = "AEGIS_METER_UNIX_PATH"
METER_PREFIX_ENV = "AEGIS_METER_PATH_PREFIX"
BROKER_UNIX_ENV = "AEGIS_TOOL_BROKER_UNIX_PATH"
BRIDGE_ONLY_ENV = "AEGIS_BRIDGE_ONLY"
WORKER_KIND_ENV = "AEGIS_WORKER_KIND"


@dataclass(frozen=True)
class TaskView:
    """Task metadata safe to hand to an isolated adapter worker."""

    workspace: Path
    id: str
    task_type: str
    title: str
    description: str
    interface: str
    candidate_sources: tuple[str, ...]
    visible: tuple[str, ...]
    schema_version: int
    experiment_use: str
    difficulty: str
    tier: str
    tool_policy: dict[str, Any]
    input_domain: dict[str, Any]
    protectability: dict[str, Any]

    @classmethod
    def from_task(cls, task: Task, workspace: Path) -> "TaskView":
        protocol = task.protocol_dict()
        return cls(
            workspace=Path(workspace),
            id=task.id,
            task_type=task.task_type,
            title=task.title,
            description=task.description,
            interface=task.interface,
            candidate_sources=task.candidate_sources,
            visible=task.visible,
            schema_version=task.schema_version,
            experiment_use=task.experiment_use,
            difficulty=task.difficulty,
            tier=task.tier,
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
            task_type=str(raw["task_type"]),
            title=str(raw["title"]),
            description=str(raw["description"]),
            interface=str(raw["interface"]),
            candidate_sources=tuple(raw["candidate_sources"]),
            visible=tuple(raw["visible"]),
            schema_version=int(raw["schema_version"]),
            experiment_use=str(raw["experiment_use"]),
            difficulty=str(raw["difficulty"]),
            tier=str(raw["tier"]),
            tool_policy=dict(raw["tool_policy"]),
            input_domain=dict(raw["input_domain"]),
            protectability=dict(raw["protectability"]),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "title": self.title,
            "description": self.description,
            "interface": self.interface,
            "candidate_sources": list(self.candidate_sources),
            "visible": list(self.visible),
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "experiment_use": self.experiment_use,
            "difficulty": self.difficulty,
            "tier": self.tier,
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
            "tier": self.tier,
            "tool_policy": self.tool_policy,
            "input_domain": self.input_domain,
            "protectability": self.protectability,
        }


class ProcessIsolatedAgent(Agent):
    """Parent-side proxy that executes one adapter call in a child process."""

    def __init__(self, inner: Agent, *, timeout_seconds: int,
                 tcp_ports: tuple[int, ...] = (),
                 network_namespace: bool = False,
                 meter_unix_path: str | None = None,
                 meter_prefix: str = "",
                 broker_unix_path: str | None = None):
        self.name = inner.name
        self.adversary = inner.adversary
        self.version = str(getattr(inner, "version", ""))
        self.adapter_options = dict(
            getattr(inner, "adapter_options", {}) or {})
        self.adapter_spec = str(
            getattr(inner, "adapter_spec", "") or "")
        if not self.adapter_spec:
            raise AdapterError(
                f"adapter {inner.name} has no importable adapter_spec for "
                f"process isolation")
        self.timeout_seconds = timeout_seconds
        self.tcp_ports = tcp_ports
        self.network_namespace = network_namespace
        self.meter_unix_path = meter_unix_path
        self.meter_prefix = meter_prefix.rstrip("/")
        self.broker_unix_path = broker_unix_path
        self.last_isolation: dict[str, Any] = {
            "adapter": "process",
            "sandbox": False,
            "filesystem": "not restricted",
            "network": "not restricted",
            "network_namespace": False,
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

    def _run_worker(
            self, request_path: Path, response_path: Path, workspace: Path,
            env: dict[str, str], timeout: int | None
            ) -> subprocess.CompletedProcess[bytes]:
        worker_command = [
            sys.executable, "-c",
            "from aegis_bench.worker import main; "
            "raise SystemExit(main())",
            str(request_path), str(response_path), str(workspace),
        ]
        if self.network_namespace:
            worker_command = [*unshare_options(), "--", *worker_command]
        return subprocess.run(
            worker_command, cwd=workspace, env=env, capture_output=True,
            timeout=timeout)

    def solve(self, task: Task, workspace: Path) -> AgentResult:
        view = TaskView.from_task(task, workspace)
        request = {
            "adapter_spec": self.adapter_spec,
            "adapter_options": self.adapter_options,
            "task": view.payload(),
        }
        env = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[1])
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            package_root + (os.pathsep + existing if existing else ""))
        if os.name == "posix" and os.environ.get("AEGIS_LANDLOCK", "1") != "0":
            env["AEGIS_LANDLOCK"] = "1"
            env["AEGIS_SECCOMP"] = "1"
            env["AEGIS_LANDLOCK_RO_PATHS"] = os.pathsep.join(
                str(path) for path in self._landlock_paths())
            env["AEGIS_LANDLOCK_TCP_PORTS"] = ",".join(
                str(port) for port in self.tcp_ports)
        if self.network_namespace:
            if os.name != "posix":
                raise AdapterError(
                    "network namespace isolation is supported only on Linux")
            env[NETNS_ENV] = "1"
            if self.meter_unix_path:
                env[METER_UNIX_ENV] = self.meter_unix_path
                env[METER_PREFIX_ENV] = self.meter_prefix
            if self.broker_unix_path:
                env[BROKER_UNIX_ENV] = self.broker_unix_path
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
                proc = self._run_worker(
                    request_path, response_path, workspace, env, timeout)
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


class ContainerIsolatedAgent(ProcessIsolatedAgent):
    """Run one adapter cell in a disposable non-root OCI container."""

    def __init__(self, inner: Agent, *, timeout_seconds: int,
                 broker_unix_path: str | None = None,
                 meter_unix_path: str | None = None,
                 meter_prefix: str = "",
                 config: ContainerConfig | None = None):
        super().__init__(
            inner, timeout_seconds=timeout_seconds,
            network_namespace=False,
            meter_unix_path=meter_unix_path,
            meter_prefix=meter_prefix,
            broker_unix_path=broker_unix_path)
        self.config = config or ContainerConfig.from_env()
        self.last_isolation = {
            "adapter": "container",
            "sandbox": False,
            "filesystem": "container filesystem not installed yet",
            "network": "container network not installed yet",
            "network_namespace": False,
            "container": {
                "runtime": self.config.runtime,
                "image": self.config.image,
                "read_only_root": True,
                "network": "none",
                "capabilities": "dropped",
                "no_new_privileges": True,
                "pids_limit": self.config.pids_limit,
                "nofile_limit": self.config.nofile_limit,
                "non_root": bool(
                    self.config.user
                    and self.config.user.split(":", 1)[0] not in ("", "0")),
            },
        }

    @staticmethod
    def _write_env_file(path: Path, env: dict[str, str]) -> None:
        lines = []
        for key, value in sorted(env.items()):
            if not key or "=" in key or "\n" in key or "\n" in value:
                raise AdapterError(
                    f"invalid container environment entry {key!r}")
            lines.append(f"{key}={value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)

    def _container_env(self, transport: Path) -> dict[str, str]:
        env = container_env()
        adapter_mounts = adapter_mounts_from_env()
        pythonpath = ["/aegis/bench", *(target for _, target in adapter_mounts)]
        env["PYTHONPATH"] = ":".join(pythonpath)
        env["LLM_SAVE_DIR"] = "/aegis/transport/submissions"
        env["AEGIS_LANDLOCK_RO_PATHS"] = ":".join([
            "/usr", "/usr/local", "/lib", "/lib64", "/bin", "/etc",
            "/aegis/bench", *(target for _, target in adapter_mounts),
        ])
        if self.broker_unix_path:
            env[BROKER_UNIX_ENV] = "/run/aegis/broker.sock"
        if self.meter_unix_path:
            env[METER_UNIX_ENV] = "/run/aegis/meter.sock"
            env[METER_PREFIX_ENV] = self.meter_prefix
        env["AEGIS_TOOL_BROKER_TOKEN"] = os.environ.get(
            "AEGIS_TOOL_BROKER_TOKEN", "")
        if not env["AEGIS_TOOL_BROKER_TOKEN"]:
            env.pop("AEGIS_TOOL_BROKER_TOKEN")
        if not transport.is_dir():
            raise AdapterError("container transport directory is missing")
        return env

    def _run_worker(
            self, request_path: Path, response_path: Path, workspace: Path,
            env: dict[str, str], timeout: int | None
            ) -> subprocess.CompletedProcess[bytes]:
        del env  # the container allowlist is built from scratch
        transport = request_path.parent
        workspace.chmod(0o777)
        transport.chmod(0o777)
        (transport / "submissions").chmod(0o777)
        container_env_values = self._container_env(transport)
        with tempfile.TemporaryDirectory(
                prefix="aegis-container-env-") as env_dir:
            env_path = Path(env_dir) / "worker.env"
            self._write_env_file(env_path, container_env_values)
            name = f"aegis-cell-{uuid.uuid4().hex[:16]}"
            package_root = Path(__file__).resolve().parents[1]
            command = build_command(
                self.config,
                name=name,
                workspace=workspace,
                transport=transport,
                package_root=package_root,
                adapter_mounts=adapter_mounts_from_env(),
                broker_socket=self.broker_unix_path,
                meter_socket=self.meter_unix_path,
                env_file=env_path,
                worker_args=(
                    "/aegis/transport/request.json",
                    "/aegis/transport/response.json",
                    "/aegis/workspace",
                ))
            try:
                return subprocess.run(
                    command, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    [self.config.runtime, "rm", "-f", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=15, check=False)
                raise


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
        worker_kind = os.environ.get(WORKER_KIND_ENV, "process")
        bridge_only = os.environ.get(BRIDGE_ONLY_ENV) == "1"
        isolation = {
            "adapter": worker_kind,
            "sandbox": False,
            "filesystem": "not restricted",
            "network": "not restricted",
            "network_namespace": False,
        }
        bridges: list[LoopbackBridge] = []
        if os.environ.get(NETNS_ENV) == "1" or bridge_only:
            try:
                if not bridge_only:
                    bring_up_loopback()
                bridge_specs = (
                    (METER_UNIX_ENV, "AEGIS_METER_BASE_URL"),
                    (BROKER_UNIX_ENV, "AEGIS_TOOL_BROKER_URL"),
                )
                for path_env, url_env in bridge_specs:
                    unix_path = os.environ.get(path_env)
                    if not unix_path:
                        continue
                    bridge = LoopbackBridge(unix_path).start()
                    bridges.append(bridge)
                    suffix = ""
                    if path_env == METER_UNIX_ENV:
                        suffix = os.environ.get(METER_PREFIX_ENV, "")
                    os.environ[url_env] = bridge.url + suffix
                if not bridges and not bridge_only:
                    raise NetnsError(
                        "network namespace is enabled but no Unix-socket "
                        "broker or meter path was supplied")
                os.environ["AEGIS_LANDLOCK_TCP_PORTS"] = ",".join(
                    str(bridge.port) for bridge in bridges)
                isolation.update({
                    "network_namespace": True,
                    "network_namespace_inode": namespace_inode(),
                    "network": (
                        "container network disabled; broker/meter reachable "
                        "only through mounted Unix-socket bridges"
                        if bridge_only else
                        "private network namespace; host reachable only "
                        "through loopback Unix-socket bridges"),
                })
            except (NetnsError, OSError) as exc:
                _write_response(response_path, {
                    "ok": False,
                    "error": f"cannot install network namespace: {exc}",
                })
                return 0
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
                bridge_roots = [
                    Path(value).parent for key in (
                        METER_UNIX_ENV, BROKER_UNIX_ENV)
                    if (value := os.environ.get(key))
                ]
                metadata = apply_landlock(
                    rw_paths=[workspace, request_path.parent, *bridge_roots],
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
        if os.environ.get("AEGIS_SECCOMP") == "1":
            try:
                isolation["seccomp"] = apply_socket_policy()
                isolation["network"] = (
                    "container network disabled; loopback Unix-socket "
                    "bridges only; UDP/raw sockets denied"
                    if worker_kind == "container" else
                    "private network namespace; loopback Unix-socket "
                    "bridges only; UDP/raw sockets denied"
                    if isolation.get("network_namespace")
                    else "Landlock TCP allowlist; UDP/raw sockets denied")
            except SeccompError as exc:
                _write_response(response_path, {
                    "ok": False,
                    "error": f"cannot install seccomp policy: {exc}",
                })
                return 0
        options = request.get("adapter_options", {})
        if not isinstance(options, dict):
            raise AdapterError("adapter_options must be an object")
        agent = create_agent(str(request["adapter_spec"]), **options)
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
