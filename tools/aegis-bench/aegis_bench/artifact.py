"""Build the stripped probe a binary-recovery task shows to the agent.

The benchmark measures what it costs to recover behaviour from a protected
binary. This module produces that binary from the task's ground truth and a
protection profile, using the local Clang/LLVM toolchain:

    source --clang(frontend IR)--> opt[pipeline] --> object --link--> probe

Only the final stripped ``probe`` enters the agent workspace. The source,
intermediate IR/objects and the ground truth stay in the harness's cache.

Builds are deterministic in their inputs (task content hash, profile, tool
paths) and are cached under ``<out_dir>/.artifacts``; the artifact's SHA-256
and size are recorded in every run row so a report names the exact binary that
was shown.

This module does not import a model SDK, open a socket, or read credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import ArtifactProfile, Task

BUILD_TIMEOUT = 180
SANITY_TIMEOUT = 10
LOG_CHARS = 4000
MAX_PROBE_BYTES = 32 * 1024 * 1024
CACHE_VERSION = "v1"


class ArtifactError(Exception):
    """A probe could not be built or failed its sanity check."""


@dataclass(frozen=True)
class BuiltArtifact:
    profile: str
    level: int
    path: Path
    sha256: str
    size_bytes: int
    text_bytes: int
    toolchain: dict[str, str]
    build_log: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "level": self.level,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "text_bytes": self.text_bytes,
            "toolchain": self.toolchain,
            "build_log": self.build_log,
        }


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def _text_bytes(path: Path) -> int:
    """Best-effort `.text` size via binutils `size` (0 if unavailable)."""
    try:
        proc = subprocess.run(["size", str(path)], capture_output=True,
                              timeout=10)
        lines = proc.stdout.decode(errors="replace").strip().splitlines()
        if proc.returncode == 0 and len(lines) >= 2:
            fields = lines[1].split()
            if fields:
                return int(fields[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return 0


class ArtifactBuilder:
    def __init__(self, *, clang: str | None = None, opt: str | None = None,
                 plugin: str | None = None,
                 cache_root: Path | None = None):
        self.clang = clang or os.environ.get("BENCH_CLANG", "clang++-23")
        self.opt = opt or os.environ.get("BENCH_OPT", "opt-23")
        self.plugin = (plugin if plugin is not None
                       else os.environ.get("AEGIS_PLUGIN"))
        self.cache_root = Path(cache_root) if cache_root else None
        self._cache: dict[tuple[str, str], BuiltArtifact] = {}
        self._toolchain: dict[str, str] | None = None
        self._fingerprint = ""

    # -- toolchain -------------------------------------------------------

    def _resolve(self, command: str) -> str | None:
        if os.path.sep in command or (os.path.altsep and os.path.altsep in command):
            return command if Path(command).is_file() else None
        return shutil.which(command)

    def _check_toolchain(self) -> None:
        if self._toolchain is not None:
            return
        clang = self._resolve(self.clang)
        opt = self._resolve(self.opt)
        if not clang:
            raise ArtifactError(f"clang not found: {self.clang!r}")
        if not opt:
            raise ArtifactError(f"opt not found: {self.opt!r}")
        plugin = self._resolve(self.plugin) if self.plugin else None
        if self.plugin and not plugin:
            raise ArtifactError(f"plugin not found: {self.plugin!r}")
        info: dict[str, str] = {"clang": clang, "opt": opt}
        if plugin:
            info["plugin"] = plugin
            try:
                info["plugin_sha256"] = hashlib.sha256(
                    Path(plugin).read_bytes()).hexdigest()
            except OSError as exc:
                raise ArtifactError(f"cannot read plugin {plugin}: {exc}") from exc
        for key, command in (("clang_version", clang), ("opt_version", opt)):
            try:
                proc = subprocess.run([command, "--version"], capture_output=True,
                                      timeout=10)
                info[key] = _first_line(proc.stdout.decode(errors="replace"))
            except (OSError, subprocess.TimeoutExpired):
                info[key] = ""
        self._toolchain = info
        fingerprint = json.dumps(info, sort_keys=True)
        self._fingerprint = hashlib.sha256(
            fingerprint.encode()).hexdigest()[:12]

    # -- process helpers -------------------------------------------------

    def _run(self, cmd: list[str], log: list[str], *,
             timeout: int = BUILD_TIMEOUT,
             input: bytes | None = None) -> subprocess.CompletedProcess:
        log.append("$ " + " ".join(cmd))
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                  input=input)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ArtifactError(f"command failed to start: {cmd[0]}: {exc}")
        text = proc.stderr.decode(errors="replace")
        if proc.returncode != 0:
            log.append(text[-LOG_CHARS:])
            raise ArtifactError(
                f"build command failed ({cmd[0]}, exit {proc.returncode}):\n"
                f"{text[-LOG_CHARS:]}")
        if text:
            # Keep the transform's selection/verification report in the
            # artifact provenance, not just the command lines.
            log.append(text[-LOG_CHARS:])
        return proc

    # -- build -----------------------------------------------------------

    def build(self, task: Task, profile: str) -> BuiltArtifact:
        recipe = task.artifact
        if recipe is None:
            raise ArtifactError(f"{task.id} is not a binary-recovery task")
        spec: ArtifactProfile | None = recipe.profiles.get(profile)
        if spec is None:
            available = ", ".join(sorted(recipe.profiles))
            raise ArtifactError(
                f"{task.id} has no artifact profile '{profile}' "
                f"(available: {available})")
        if spec.level > 0 and not self.plugin:
            raise ArtifactError(
                f"{task.id}/{profile} is level {spec.level} but no plugin was "
                f"given; pass --plugin or set AEGIS_PLUGIN")

        self._check_toolchain()
        assert self._toolchain is not None
        key = (task.id, profile)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if self.cache_root is not None:
            digest = task.content_hash.split(":", 1)[-1][:16]
            build_dir = (self.cache_root / task.id /
                         f"{CACHE_VERSION}-{profile}-{digest}-{self._fingerprint}")
            build_dir.mkdir(parents=True, exist_ok=True)
        else:
            build_dir = Path(tempfile.mkdtemp(prefix=f"aegis-art-{task.id}-"))

        meta_path = build_dir / "artifact.json"
        probe_name = "probe.exe" if os.name == "nt" else "probe"
        probe_path = build_dir / probe_name
        if probe_path.is_file() and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            built = BuiltArtifact(
                profile=profile, level=spec.level, path=probe_path,
                sha256=meta["sha256"], size_bytes=meta["size_bytes"],
                text_bytes=_text_bytes(probe_path),
                toolchain=meta["toolchain"],
                build_log=meta.get("build_log", ""))
            self._cache[key] = built
            return built

        source = task.path(recipe.source)
        probe_src = task.path(recipe.probe)
        includes: list[str] = []
        for directory in recipe.include_dirs:
            includes += ["-I", str(task.path(directory))]
        includes += ["-I", str(probe_src.parent)]

        ir = build_dir / "target.frontend.ll"
        opt_ir = build_dir / "target.optimized.ll"
        obj = build_dir / "target.o"
        log: list[str] = [f"task={task.id} profile={profile} "
                          f"level={spec.level}"]

        self._run([self._toolchain["clang"], "-std=c++17", "-O2", "-g0",
                   "-Xclang", "-disable-llvm-passes", "-S", "-emit-llvm",
                   str(source), *includes, "-o", str(ir)], log)

        if spec.level == 0:
            self._run([self._toolchain["opt"], "-passes=default<O2>",
                       str(ir), "-S", "-o", str(opt_ir)], log)
        else:
            assert spec.policy is not None
            policy = task.path(spec.policy)
            if any(ch in str(policy) for ch in ",<>"):
                raise ArtifactError(
                    f"policy path cannot be encoded in a pass name: {policy}")
            passes = (f"aegis-policy<policy={policy}>,aegis-decoys"
                      + (",aegis-cff" if spec.level >= 2 else "")
                      + ",default<O2>,aegis-verify")
            self._run([self._toolchain["opt"],
                       f"-load-pass-plugin={self._toolchain['plugin']}",
                       f"-passes={passes}", str(ir), "-S", "-o",
                       str(opt_ir)], log)

        self._run([self._toolchain["clang"], "-std=c++17", "-O2", "-c",
                   str(opt_ir), "-o", str(obj)], log)
        self._run([self._toolchain["clang"], "-std=c++17", "-O2",
                   str(probe_src), str(obj), *includes, "-s", "-o",
                   str(probe_path)], log)

        if not probe_path.is_file():
            raise ArtifactError(f"probe was not produced: {probe_path}")
        size = probe_path.stat().st_size
        if size > MAX_PROBE_BYTES:
            raise ArtifactError(f"probe is unexpectedly large ({size} bytes)")

        try:
            sanity = self._run([str(probe_path)], log, timeout=SANITY_TIMEOUT,
                               input=b"")
        except ArtifactError as exc:
            raise ArtifactError(f"probe failed its empty-input sanity run: "
                                f"{exc}") from exc
        if b"hash=" not in sanity.stdout:
            raise ArtifactError("probe did not print the documented output on "
                                "empty input")

        data = probe_path.read_bytes()
        text_bytes = _text_bytes(probe_path)
        log_text = "\n".join(log)
        for prefix, label in ((str(task.root.resolve()), "<task>"),
                              (str(build_dir), "<build>")):
            log_text = log_text.replace(prefix, label)
        meta = {
            "profile": profile,
            "level": spec.level,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": size,
            "text_bytes": text_bytes,
            "toolchain": self._toolchain,
            "build_log": log_text[-LOG_CHARS:],
        }
        meta_path.write_text(json.dumps(meta, indent=2) + "\n",
                             encoding="utf-8")
        built = BuiltArtifact(profile=profile, level=spec.level,
                              path=probe_path, sha256=meta["sha256"],
                              size_bytes=size, text_bytes=text_bytes,
                              toolchain=self._toolchain,
                              build_log=meta["build_log"])
        self._cache[key] = built
        return built
