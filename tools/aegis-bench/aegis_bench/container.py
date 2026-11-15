"""Container-per-cell isolation command construction.

The harness talks to an ordinary OCI runtime CLI. This module only builds the
security boundary; it does not imply that the host daemon is rootless. The
report records the actual runtime and image so that distinction is visible.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ContainerError(Exception):
    """The container isolation boundary cannot be installed."""


@dataclass(frozen=True)
class ContainerConfig:
    runtime: str = "docker"
    image: str = "aegis-ir-dev"
    memory: str = "1g"
    cpus: str = "2"
    pids_limit: int = 128
    nofile_limit: int = 256
    user: str = ""

    @classmethod
    def from_env(cls) -> "ContainerConfig":
        user = os.environ.get("AEGIS_CONTAINER_USER", "65534:65534")
        return cls(
            runtime=os.environ.get("AEGIS_CONTAINER_RUNTIME", "docker"),
            image=os.environ.get(
                "AEGIS_CONTAINER_IMAGE", "aegis-ir-dev"),
            memory=os.environ.get("AEGIS_CONTAINER_MEMORY", "1g"),
            cpus=os.environ.get("AEGIS_CONTAINER_CPUS", "2"),
            pids_limit=int(os.environ.get(
                "AEGIS_CONTAINER_PIDS_LIMIT", "128")),
            nofile_limit=int(os.environ.get(
                "AEGIS_CONTAINER_NOFILE_LIMIT", "256")),
            user=user)

    def validate(self) -> None:
        if shutil.which(self.runtime) is None:
            raise ContainerError(
                f"container runtime not found: {self.runtime}")
        if not self.image or any(ch.isspace() for ch in self.image):
            raise ContainerError(
                f"invalid container image: {self.image!r}")
        if self.pids_limit < 16 or self.nofile_limit < 64:
            raise ContainerError(
                "container pids/nofile limits are unrealistically low")
        for name, value in (("memory", self.memory), ("cpus", self.cpus)):
            if not value or any(ch.isspace() for ch in value):
                raise ContainerError(
                    f"invalid container {name}: {value!r}")

    def preflight(self) -> None:
        """Fail before a campaign cell if the runtime or image is absent."""
        self.validate()
        if os.environ.get("AEGIS_CONTAINER_SKIP_IMAGE_CHECK") == "1":
            return
        result = subprocess.run(
            [self.runtime, "image", "inspect", self.image],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=30, check=False)
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            raise ContainerError(
                f"container image {self.image!r} is unavailable: {detail}")


def _mount(source: Path, target: str, *, readonly: bool) -> list[str]:
    spec = f"type=bind,source={source.resolve()},target={target}"
    if readonly:
        spec += ",readonly"
    return ["--mount", spec]


def build_command(
        config: ContainerConfig,
        *,
        name: str,
        workspace: Path,
        transport: Path,
        package_root: Path,
        adapter_mounts: tuple[tuple[Path, str], ...],
        broker_socket: str | None,
        meter_socket: str | None,
        env_file: Path,
        worker_args: tuple[str, ...],
        ) -> list[str]:
    """Return a fail-closed, per-cell container command."""
    config.validate()
    if not name or any(ch.isspace() for ch in name):
        raise ContainerError(f"invalid container name: {name!r}")
    command = [
        config.runtime, "run", "--rm", "--init",
        "--name", name,
        "--pull=never",
        "--read-only",
        "--network=none",
        "--ipc=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        f"--pids-limit={config.pids_limit}",
        f"--memory={config.memory}",
        f"--cpus={config.cpus}",
        f"--ulimit=nofile={config.nofile_limit}:{config.nofile_limit}",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--env-file", str(env_file.resolve()),
        "--workdir", "/aegis/workspace",
    ]
    if config.user:
        command += ["--user", config.user]
    command += _mount(package_root, "/aegis/bench", readonly=True)
    command += _mount(workspace, "/aegis/workspace", readonly=False)
    command += _mount(transport, "/aegis/transport", readonly=False)
    seen: set[Path] = set()
    for source, target in adapter_mounts:
        resolved = source.resolve()
        if resolved in seen or resolved == package_root.resolve():
            continue
        seen.add(resolved)
        command += _mount(resolved, target, readonly=True)
    if broker_socket:
        command += _mount(
            Path(broker_socket), "/run/aegis/broker.sock", readonly=False)
    if meter_socket:
        command += _mount(
            Path(meter_socket), "/run/aegis/meter.sock", readonly=False)
    command += [
        config.image, "python3", "-c",
        "from aegis_bench.worker import main; raise SystemExit(main())",
        *worker_args,
    ]
    return command


def adapter_mounts_from_env() -> tuple[tuple[Path, str], ...]:
    mounts: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for value in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if not value:
            continue
        path = Path(value).resolve()
        if path.is_dir() and path not in seen:
            seen.add(path)
            mounts.append((path, f"/aegis/adapters/{len(mounts)}"))
    return tuple(mounts)


def container_env() -> dict[str, str]:
    """Return the small, explicit environment allowlist for a worker."""
    names = {
        "LLM_API_KEY", "ZCODE_API_KEY",
        "LLM_BASE_URL", "ZCODE_BASE_URL",
        "LLM_MODEL", "ZCODE_MODEL",
        "AEGIS_TOOL_BROKER_TOKEN",
    }
    extra = os.environ.get("AEGIS_CONTAINER_ENV", "")
    names.update(item.strip() for item in extra.split(",") if item.strip())
    env = {name: os.environ[name] for name in sorted(names)
           if name in os.environ}
    env.update({
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AEGIS_WORKER_KIND": "container",
        "AEGIS_BRIDGE_ONLY": "1",
        "AEGIS_LANDLOCK": "1",
        "AEGIS_SECCOMP": "1",
    })
    return env
