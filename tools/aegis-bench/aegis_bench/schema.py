"""Task manifests: parsing, validation and content-integrity hashing.

A task is a directory containing a ``task.json`` manifest plus the files it
names. Everything the agent may see is listed under ``visible``; everything
else (ground truth, property tests, hidden cases) stays out of the workspace.

Manifest shape (schema_version 1)::

    {
      "schema_version": 1,
      "id": "fnv-rolling-hash-v1",
      "title": "Recover a rolling hash and token predicate",
      "description": "task.md",
      "interface": "include/target.h",
      "candidate_sources": ["target.cpp"],
      "visible": ["task.md", "include/target.h", "examples/"],
      "ground_truth": "ground_truth/target.cpp",
      "properties": "grader/properties.cpp",
      "driver": "grader/driver.cpp",
      "hidden_cases": ["grader/hidden/case-000.bin", ...],
      "fuzz": {"cases": 64, "seed": 1234, "max_len": 4096},
      "budgets": {"max_tool_calls": 200, "timeout_seconds": 600,
                  "max_output_tokens": 200000},
      "protectability": {"domain_size": "small", "rating": "high"},
      "content_hash": "sha256:..."
    }
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class TaskError(Exception):
    """A manifest is malformed or the task directory is inconsistent."""


@dataclass(frozen=True)
class Budget:
    max_tool_calls: int = 200
    timeout_seconds: int = 600
    max_output_tokens: int = 200_000

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Budget":
        return cls(
            max_tool_calls=int(raw.get("max_tool_calls", 200)),
            timeout_seconds=int(raw.get("timeout_seconds", 600)),
            max_output_tokens=int(raw.get("max_output_tokens", 200_000)),
        )


@dataclass(frozen=True)
class FuzzConfig:
    cases: int = 64
    seed: int = 1234
    max_len: int = 4096

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FuzzConfig":
        return cls(
            cases=int(raw.get("cases", 64)),
            seed=int(raw.get("seed", 1234)),
            max_len=int(raw.get("max_len", 4096)),
        )


@dataclass(frozen=True)
class Task:
    root: Path
    id: str
    title: str
    description: str
    interface: str
    candidate_sources: tuple[str, ...]
    visible: tuple[str, ...]
    ground_truth: str
    properties: str
    driver: str
    hidden_cases: tuple[str, ...]
    fuzz: FuzzConfig
    budgets: Budget
    protectability: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    # -- helpers ---------------------------------------------------------

    def path(self, relative: str) -> Path:
        """Resolve a manifest-relative path, refusing to escape the task."""
        candidate = (self.root / relative).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise TaskError(f"path escapes task root: {relative}")
        return candidate

    def hidden_paths(self) -> list[Path]:
        return [self.path(c) for c in self.hidden_cases]

    def computed_hash(self) -> str:
        """SHA-256 over every file the manifest names, in manifest order.

        The hash covers the grader inputs as well as the visible files, so a
        silently edited property test invalidates a recorded result.

        Line endings are normalised to LF before hashing. Without this, the
        same commit produces different hashes on a Windows working copy
        (CRLF) and a Linux checkout (LF), and every CI run would report a
        spurious mismatch. Normalisation is applied uniformly to both sides,
        so it never hides a content edit.
        """
        digest = hashlib.sha256()
        root = self.root.resolve()

        def feed(name: str, data: bytes) -> None:
            digest.update(name.encode())
            digest.update(b"\0")
            digest.update(data.replace(b"\r\n", b"\n"))

        names: list[str] = [self.description, self.interface,
                            self.ground_truth, self.properties, self.driver]
        names += list(self.visible)
        names += list(self.hidden_cases)
        for name in names:
            path = self.path(name)
            if path.is_dir():
                for child in sorted(p for p in path.rglob("*") if p.is_file()):
                    rel = child.resolve().relative_to(root).as_posix()
                    feed(rel, child.read_bytes())
            elif path.is_file():
                feed(name, path.read_bytes())
            else:
                raise TaskError(f"manifest names a missing path: {name}")
        return "sha256:" + digest.hexdigest()


def _require(raw: dict[str, Any], key: str, kind: type) -> Any:
    if key not in raw:
        raise TaskError(f"missing required key: {key}")
    value = raw[key]
    if not isinstance(value, kind):
        raise TaskError(f"'{key}' must be {kind.__name__}, "
                        f"got {type(value).__name__}")
    return value


def load_task(task_dir: str | Path, *, verify_hash: bool = True) -> Task:
    root = Path(task_dir)
    manifest_path = root / "task.json"
    if not manifest_path.is_file():
        raise TaskError(f"no task.json in {root}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"{manifest_path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise TaskError(f"{manifest_path}: top level must be an object")

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise TaskError(f"unsupported schema_version {version!r} "
                        f"(expected {SCHEMA_VERSION})")

    sources = _require(raw, "candidate_sources", list)
    if not sources:
        raise TaskError("candidate_sources must not be empty")

    task = Task(
        root=root,
        id=_require(raw, "id", str),
        title=_require(raw, "title", str),
        description=_require(raw, "description", str),
        interface=_require(raw, "interface", str),
        candidate_sources=tuple(sources),
        visible=tuple(_require(raw, "visible", list)),
        ground_truth=_require(raw, "ground_truth", str),
        properties=_require(raw, "properties", str),
        driver=_require(raw, "driver", str),
        hidden_cases=tuple(_require(raw, "hidden_cases", list)),
        fuzz=FuzzConfig.from_dict(raw.get("fuzz", {})),
        budgets=Budget.from_dict(raw.get("budgets", {})),
        protectability=raw.get("protectability", {}),
        content_hash=str(raw.get("content_hash", "")),
    )

    # Resolve every named path now so a broken task fails at load, not after
    # an agent has already spent its budget.
    for name in (*task.visible, task.description, task.interface,
                 task.ground_truth, task.properties, task.driver,
                 *task.hidden_cases):
        if not task.path(name).exists():
            raise TaskError(f"{task.id}: missing file '{name}'")
    for name in task.candidate_sources:
        if "/" in name or "\\" in name:
            raise TaskError(f"{task.id}: candidate source must be a bare "
                            f"filename, got '{name}'")

    if verify_hash:
        if not task.content_hash:
            raise TaskError(f"{task.id}: content_hash missing; run "
                            f"'aegis-bench hash <task-dir>' to set it")
        actual = task.computed_hash()
        if actual != task.content_hash:
            raise TaskError(
                f"{task.id}: content hash mismatch\n  manifest: "
                f"{task.content_hash}\n  actual:   {actual}\n"
                "The task files changed after the hash was recorded.")
    return task


def discover_tasks(root: str | Path, *, verify_hash: bool = True) -> list[Task]:
    root = Path(root)
    if not root.is_dir():
        raise TaskError(f"no such task directory: {root}")
    tasks = []
    for manifest in sorted(root.glob("*/task.json")):
        tasks.append(load_task(manifest.parent, verify_hash=verify_hash))
    if not tasks:
        raise TaskError(f"no tasks found under {root}")
    return tasks
