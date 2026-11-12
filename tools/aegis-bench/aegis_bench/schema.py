"""Task manifests: parsing, validation and content-integrity hashing.

A task is a directory containing a ``task.json`` manifest plus the files it
names. Everything the agent may see is listed under ``visible``; everything
else (ground truth, property tests, hidden cases) stays out of the workspace.

Manifest shape (schema_version 2; version 1 remains readable)::

    {
      "schema_version": 2,
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
                  "max_output_tokens": 200000,
                  "oracle_queries": 200},   # optional; capped by the broker
      "protectability": {"domain_size": "small", "rating": "high"},
      "experiment_use": "harness-validation",
      "difficulty": "small",
      "tool_policy": {
        "allowed_tools": ["list_files", "read_file", "run_probe",
                          "disassemble", "submit_solution"],
        "network": "metered_model",
        "workspace_writable": true
      },
      "input_domain": {"kind": "bytes", "summary": "..."},
      "content_hash": "sha256:...",

      # Optional. "reimplement" (default) gives the agent a brief and
      # examples; "binary-recovery" also builds a stripped probe per profile.
      "task_type": "binary-recovery",
      "artifact": {
        "source": "ground_truth/target.cpp",   # must equal ground_truth
        "probe": "grader/driver.cpp",          # linked into the probe
        "include_dirs": ["include"],
        "profiles": {
          "baseline": {"level": 0},
          "aegis-level3": {"level": 3,
                           "policy": "grader/policies/level3.json"}
        }
      }
    }
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class TaskError(Exception):
    """A manifest is malformed or the task directory is inconsistent."""


@dataclass(frozen=True)
class Budget:
    max_tool_calls: int = 200
    timeout_seconds: int = 600
    max_output_tokens: int = 200_000
    #: Cap on oracle queries for binary-recovery tasks; ``None`` counts but
    #: does not cap. Enforced by the harness broker, not by the adapter.
    oracle_queries: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Budget":
        oracle = raw.get("oracle_queries")
        if oracle is not None and (isinstance(oracle, bool)
                                   or not isinstance(oracle, int)
                                   or oracle < 0):
            raise TaskError("budgets.oracle_queries must be a non-negative "
                            "integer")
        return cls(
            max_tool_calls=int(raw.get("max_tool_calls", 200)),
            timeout_seconds=int(raw.get("timeout_seconds", 600)),
            max_output_tokens=int(raw.get("max_output_tokens", 200_000)),
            oracle_queries=oracle,
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


TASK_TYPES = ("reimplement", "binary-recovery")
TASK_TOOLS = (
    "list_files", "read_file", "run_probe", "disassemble", "submit_solution",
)
NETWORK_POLICIES = ("none", "metered_model", "legacy-unspecified")
EXPERIMENT_USES = ("harness-validation", "pilot", "comparison")
DIFFICULTIES = ("small", "medium", "large")
INPUT_DOMAIN_KINDS = ("bytes", "structured")
DOMAIN_SIZES = ("small", "medium", "large", "unbounded")
PROTECTABILITY_RATINGS = ("low", "medium", "high")

#: What a binary-recovery workspace gets. Defined here so both the manifest
#: validation and the runner agree on the spelling; see the runner for what
#: each mode does.
ACCESS_MODES = ("oracle", "binary")

CALIBRATION_STATUSES = ("uncalibrated", "floor", "ceiling", "comparison-ready")


@dataclass(frozen=True)
class ToolPolicy:
    """Declared adapter tool surface for a task.

    The harness records this contract but does not enforce it for an
    in-process adapter. Process isolation and a harness-owned tool RPC are the
    enforcement step; this schema makes the gap explicit and auditable rather
    than implicit.
    """

    allowed_tools: tuple[str, ...]
    network: str
    workspace_writable: bool

    @classmethod
    def legacy(cls) -> "ToolPolicy":
        return cls(allowed_tools=(), network="legacy-unspecified",
                   workspace_writable=True)

    @classmethod
    def from_dict(cls, raw: Any, task_id: str) -> "ToolPolicy":
        if not isinstance(raw, dict):
            raise TaskError(f"{task_id}: tool_policy must be an object")
        tools = raw.get("allowed_tools")
        if (not isinstance(tools, list) or not tools
                or not all(isinstance(tool, str) for tool in tools)):
            raise TaskError(
                f"{task_id}: tool_policy.allowed_tools must be a non-empty "
                f"list of strings")
        if len(set(tools)) != len(tools):
            raise TaskError(
                f"{task_id}: tool_policy.allowed_tools contains duplicates")
        unknown = set(tools) - set(TASK_TOOLS)
        if unknown:
            raise TaskError(
                f"{task_id}: unknown tool(s): {', '.join(sorted(unknown))}")
        network = raw.get("network")
        if network not in NETWORK_POLICIES[:-1]:
            raise TaskError(
                f"{task_id}: tool_policy.network must be one of "
                f"{NETWORK_POLICIES[:-1]}")
        writable = raw.get("workspace_writable")
        if not isinstance(writable, bool):
            raise TaskError(
                f"{task_id}: tool_policy.workspace_writable must be boolean")
        return cls(tuple(tools), network, writable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_tools": list(self.allowed_tools),
            "network": self.network,
            "workspace_writable": self.workspace_writable,
        }


@dataclass(frozen=True)
class Calibration:
    """How hard the task's *unprotected* baseline is for a named agent.

    A protection comparison can only measure something if the baseline itself
    succeeds sometimes: at 0/N the protected profile has nowhere to fall to, and
    at N/N there is nothing left to slow down. This record is measurement
    metadata, not task semantics — it is deliberately outside ``content_hash``
    and does not force a new task id. It is also access- and model-specific, so
    a run under a different access mode or model has to recalibrate.
    """

    status: str = "uncalibrated"
    model: str = ""
    access: str = ""
    baseline_pass_rate: float | None = None
    runs: int = 0
    date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "access": self.access,
            "baseline_pass_rate": self.baseline_pass_rate,
            "runs": self.runs,
            "date": self.date,
        }

    def is_comparison_ready(self) -> bool:
        return self.status == "comparison-ready"


def _calibration_entry(raw: Any, task_id: str, access: str) -> Calibration:
    if not isinstance(raw, dict):
        raise TaskError(f"{task_id}: calibration['{access}'] must be an object")
    status = raw.get("status", "uncalibrated")
    if status not in CALIBRATION_STATUSES:
        raise TaskError(
            f"{task_id}: calibration['{access}'].status must be one of "
            f"{CALIBRATION_STATUSES}, got {status!r}")
    if status == "uncalibrated":
        return Calibration(status=status, access=access)
    runs = raw.get("runs", 0)
    if not isinstance(runs, int) or runs < 1:
        raise TaskError(f"{task_id}: calibration['{access}'].runs must be a "
                        f"positive int")
    rate = raw.get("baseline_pass_rate")
    if not isinstance(rate, (int, float)) or not 0.0 <= float(rate) <= 1.0:
        raise TaskError(f"{task_id}: calibration['{access}']."
                        f"baseline_pass_rate must be a number in [0, 1]")
    if status == "floor" and float(rate) != 0.0:
        raise TaskError(f"{task_id}: calibration.status 'floor' requires a "
                        f"0.0 baseline pass rate")
    if status == "ceiling" and float(rate) != 1.0:
        raise TaskError(f"{task_id}: calibration.status 'ceiling' requires a "
                        f"1.0 baseline pass rate")
    if status == "comparison-ready" and not 0.0 < float(rate) < 1.0:
        raise TaskError(f"{task_id}: 'comparison-ready' needs a baseline pass "
                        f"rate strictly between 0 and 1")
    for key in ("model", "date"):
        if not str(raw.get(key, "")).strip():
            raise TaskError(f"{task_id}: calibration.{key} is required once "
                            f"a task is calibrated")
    return Calibration(status=status, model=str(raw["model"]), access=access,
                       baseline_pass_rate=float(rate), runs=runs,
                       date=str(raw["date"]))


def _calibrations(raw: Any, task_id: str) -> dict[str, Calibration]:
    """Parse ``{"oracle": {...}, "binary": {...}}`` keyed by access mode.

    One record per access mode, because the same task can be at the floor for a
    black-box agent and solvable for one that can read the binary. A single
    flat record would silently describe only one of those runs.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TaskError(f"{task_id}: 'calibration' must be an object keyed by "
                        f"access mode ({', '.join(ACCESS_MODES)})")
    out: dict[str, Calibration] = {}
    for access, entry in raw.items():
        if access not in ACCESS_MODES:
            raise TaskError(f"{task_id}: calibration key must be one of "
                            f"{ACCESS_MODES}, got {access!r}")
        out[access] = _calibration_entry(entry, task_id, access)
    return out


@dataclass(frozen=True)
class ArtifactProfile:
    """One protection profile that the runner can build into a probe."""

    level: int
    policy: str | None = None


@dataclass(frozen=True)
class ArtifactRecipe:
    """How to build a stripped probe for a binary-recovery task.

    The runner builds the probe from ``source`` + ``probe``; only the binary
    reaches the agent workspace. ``profiles`` maps the CLI's ``--profile``
    names to a policy level and (for level >= 1) the Aegis policy file that
    selects functions in ``source``.
    """

    source: str
    probe: str
    include_dirs: tuple[str, ...]
    profiles: dict[str, ArtifactProfile]


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
    task_type: str = "reimplement"
    artifact: ArtifactRecipe | None = None
    private: bool = False
    calibration: dict[str, Calibration] = field(default_factory=dict)
    schema_version: int = 1
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy.legacy)
    input_domain: dict[str, Any] = field(default_factory=dict)
    experiment_use: str = "harness-validation"
    difficulty: str = "small"

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

    def protocol_dict(self) -> dict[str, Any]:
        """Schema metadata copied into every run row for later audit."""
        return {
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "experiment_use": self.experiment_use,
            "difficulty": self.difficulty,
            "tool_policy": self.tool_policy.to_dict(),
            "input_domain": dict(self.input_domain),
            "protectability": dict(self.protectability),
        }

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
        if self.artifact is not None:
            names += [self.artifact.source, self.artifact.probe]
            names += list(self.artifact.include_dirs)
            names += [p.policy for p in self.artifact.profiles.values()
                      if p.policy]
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


def _parse_input_domain(raw: Any, task_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskError(f"{task_id}: input_domain must be an object")
    kind = raw.get("kind")
    if kind not in INPUT_DOMAIN_KINDS:
        raise TaskError(
            f"{task_id}: input_domain.kind must be one of "
            f"{INPUT_DOMAIN_KINDS}")
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise TaskError(f"{task_id}: input_domain.summary is required")
    return dict(raw)


def _parse_protectability(raw: Any, task_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskError(f"{task_id}: protectability must be an object")
    size = raw.get("domain_size")
    rating = raw.get("rating")
    if size not in DOMAIN_SIZES:
        raise TaskError(
            f"{task_id}: protectability.domain_size must be one of "
            f"{DOMAIN_SIZES}")
    if rating not in PROTECTABILITY_RATINGS:
        raise TaskError(
            f"{task_id}: protectability.rating must be one of "
            f"{PROTECTABILITY_RATINGS}")
    return dict(raw)


def _parse_artifact(raw: Any, task_id: str) -> ArtifactRecipe:
    if not isinstance(raw, dict):
        raise TaskError(f"{task_id}: 'artifact' must be an object")
    source = _require(raw, "source", str)
    probe = _require(raw, "probe", str)
    include_dirs = raw.get("include_dirs", [])
    if not isinstance(include_dirs, list) or not all(
            isinstance(d, str) for d in include_dirs):
        raise TaskError(f"{task_id}: artifact.include_dirs must be a list of "
                        f"strings")
    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise TaskError(f"{task_id}: artifact.profiles must be a non-empty "
                        f"object")
    profiles: dict[str, ArtifactProfile] = {}
    for name, spec in raw_profiles.items():
        if not isinstance(name, str) or not _PROFILE_NAME.match(name):
            raise TaskError(f"{task_id}: invalid artifact profile name "
                            f"{name!r} (use [a-z0-9][a-z0-9_-]*)")
        if not isinstance(spec, dict):
            raise TaskError(f"{task_id}: profile '{name}' must be an object")
        level = spec.get("level")
        if isinstance(level, bool) or not isinstance(level, int) or not (
                0 <= level <= 3):
            raise TaskError(f"{task_id}: profile '{name}' level must be an "
                            f"integer in 0..3")
        policy = spec.get("policy")
        if level == 0:
            if policy is not None:
                raise TaskError(f"{task_id}: profile '{name}' is level 0 and "
                                f"must not name a policy")
        else:
            if not isinstance(policy, str) or not policy:
                raise TaskError(f"{task_id}: profile '{name}' at level {level} "
                                f"requires a policy file")
            if "," in policy:
                raise TaskError(f"{task_id}: policy path '{policy}' contains a "
                                f"comma, which the pass-name parser cannot carry")
        profiles[name] = ArtifactProfile(level=level, policy=policy)
    return ArtifactRecipe(source=source, probe=probe,
                          include_dirs=tuple(include_dirs),
                          profiles=profiles)


def _validate_policy(path: Path, level: int, task_id: str,
                     profile: str) -> None:
    """Minimal cross-check that a policy actually asks for this level.

    The C++ parser performs the full validation at build time. This check
    exists so a mislabelled profile (say, a level-3 artifact built from a
    level-1 policy) fails when the task is loaded, not after a run.
    """
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskError(f"{task_id}: cannot read policy '{path.name}': "
                        f"{exc}") from exc
    if not isinstance(policy, dict):
        raise TaskError(f"{task_id}: policy '{path.name}' must be an object")
    if policy.get("schema_version") != 1:
        raise TaskError(f"{task_id}: policy '{path.name}' has unsupported "
                        f"schema_version")
    seed = policy.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not (
            0 <= seed <= 2**32 - 1):
        raise TaskError(f"{task_id}: policy '{path.name}' needs an integer "
                        f"seed in [0, 2^32-1] so the artifact is reproducible")
    functions = policy.get("functions")
    if not isinstance(functions, list) or not functions:
        raise TaskError(f"{task_id}: policy '{path.name}' must select at "
                        f"least one function")
    for entry in functions:
        if not isinstance(entry, dict):
            raise TaskError(f"{task_id}: policy '{path.name}' has a malformed "
                            f"function entry")
        name = entry.get("name")
        entry_level = entry.get("level")
        if not isinstance(name, str) or not name:
            raise TaskError(f"{task_id}: policy '{path.name}' has an entry "
                            f"without a name")
        if entry_level != level:
            raise TaskError(
                f"{task_id}: profile '{profile}' is level {level}, but policy "
                f"'{path.name}' selects '{name}' at level {entry_level}")


def load_task(task_dir: str | Path, *, verify_hash: bool = True,
              allow_private: bool = False) -> Task:
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
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TaskError(f"unsupported schema_version {version!r} "
                        f"(supported: {SUPPORTED_SCHEMA_VERSIONS})")

    sources = _require(raw, "candidate_sources", list)
    if not sources:
        raise TaskError("candidate_sources must not be empty")

    task_id = _require(raw, "id", str)
    if not _TASK_ID.match(task_id):
        raise TaskError(
            f"invalid task id {task_id!r} (use [a-z0-9][a-z0-9._-]*)")
    task_type = raw.get("task_type", "reimplement")
    if task_type not in TASK_TYPES:
        raise TaskError(f"{task_id}: task_type must be one of {TASK_TYPES}, "
                        f"got {task_type!r}")
    artifact_raw = raw.get("artifact")
    if task_type == "binary-recovery":
        artifact = _parse_artifact(artifact_raw, task_id)
    else:
        if artifact_raw is not None:
            raise TaskError(f"{task_id}: 'artifact' is only valid for "
                            f"task_type 'binary-recovery'")
        artifact = None

    if version == 2:
        if "tool_policy" not in raw:
            raise TaskError(f"{task_id}: schema_version 2 requires tool_policy")
        if "input_domain" not in raw:
            raise TaskError(
                f"{task_id}: schema_version 2 requires input_domain")
        if "experiment_use" not in raw:
            raise TaskError(
                f"{task_id}: schema_version 2 requires experiment_use")
        if "protectability" not in raw:
            raise TaskError(
                f"{task_id}: schema_version 2 requires protectability")
    tool_policy = (
        ToolPolicy.from_dict(raw["tool_policy"], task_id)
        if version == 2 else ToolPolicy.legacy())
    input_domain = (
        _parse_input_domain(raw["input_domain"], task_id)
        if version == 2 else {})
    protectability = (
        _parse_protectability(raw["protectability"], task_id)
        if version == 2 else dict(raw.get("protectability", {})))
    experiment_use = raw.get("experiment_use", "harness-validation")
    if experiment_use not in EXPERIMENT_USES:
        raise TaskError(
            f"{task_id}: experiment_use must be one of {EXPERIMENT_USES}")
    difficulty = raw.get("difficulty", "small")
    if difficulty not in DIFFICULTIES:
        raise TaskError(
            f"{task_id}: difficulty must be one of {DIFFICULTIES}")

    task = Task(
        root=root,
        id=task_id,
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
        protectability=protectability,
        content_hash=str(raw.get("content_hash", "")),
        task_type=task_type,
        artifact=artifact,
        private=_require(raw, "private", bool) if "private" in raw else False,
        calibration=_calibrations(raw.get("calibration"), task_id),
        schema_version=version,
        tool_policy=tool_policy,
        input_domain=input_domain,
        experiment_use=experiment_use,
        difficulty=difficulty,
    )

    # Private tasks live outside the public tree and their results are never
    # published; refuse to load one unless the caller opted in explicitly.
    if task.private and not allow_private:
        raise TaskError(
            f"{task.id}: private task; pass --allow-private to run it")

    if task.artifact is not None and task.artifact.source != task.ground_truth:
        raise TaskError(f"{task.id}: artifact.source must be the same file as "
                        f"ground_truth; the probe the agent reverses and the "
                        f"grader's reference must be built from one source")

    # Resolve every named path now so a broken task fails at load, not after
    # an agent has already spent its budget.
    for name in (*task.visible, task.description, task.interface,
                 task.ground_truth, task.properties, task.driver,
                 *task.hidden_cases):
        if not task.path(name).exists():
            raise TaskError(f"{task.id}: missing file '{name}'")
    if task.artifact is not None:
        artifact_paths = (task.artifact.source, task.artifact.probe,
                          *task.artifact.include_dirs)
        for name in artifact_paths:
            if not task.path(name).exists():
                raise TaskError(f"{task.id}: missing artifact path '{name}'")
        for profile, spec in task.artifact.profiles.items():
            if spec.policy is None:
                continue
            policy_path = task.path(spec.policy)
            if not policy_path.is_file():
                raise TaskError(f"{task.id}: profile '{profile}' names a "
                                f"missing policy '{spec.policy}'")
            _validate_policy(policy_path, spec.level, task.id, profile)
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


def discover_tasks(root: str | Path, *, verify_hash: bool = True,
                   allow_private: bool = False) -> list[Task]:
    root = Path(root)
    if not root.is_dir():
        raise TaskError(f"no such task directory: {root}")
    tasks = []
    for manifest in sorted(root.glob("*/task.json")):
        tasks.append(load_task(manifest.parent, verify_hash=verify_hash,
                               allow_private=allow_private))
    if not tasks:
        raise TaskError(f"no tasks found under {root}")
    return tasks
