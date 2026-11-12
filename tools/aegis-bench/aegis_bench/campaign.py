"""Resumable experiment campaigns for Aegis-Bench.

``aegis-bench run`` executes one profile per invocation. A real comparison
needs a matrix, fresh adapter instances, stable cell identity, and a recovery
path after a long run is interrupted. This module owns that orchestration:

* parse an experiment manifest and fingerprint its exact contents;
* expand the matrix into uniquely keyed cells;
* interleave repetitions so model/relay drift does not land entirely in one
  profile arm;
* persist atomic reports after every cell;
* resume by skipping rows already present in the output JSONL.

The harness, not the adapter, owns the campaign. An adapter repository should
contain only the model interaction, never a bespoke loop that writes rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from .agent import Agent, AdapterError, create_agent
from .report import atomic_write_text, write_reports
from .runner import ACCESS_MODES, Runner, RunRecord, environment_stamp
from .schema import Task, TaskError, discover_tasks

EXPERIMENT_SCHEMA_VERSION = 1
PURPOSES = ("harness-validation", "pilot", "experiment")
PRIMARY_METRICS = ("pass_rate", "tokens", "wall_seconds", "oracle_queries")
ORDERS = ("interleaved", "randomized", "sequential")
_ALLOWED_KEYS = {
    "schema_version", "name", "purpose", "primary_metric", "tasks_root",
    "tasks", "agents", "profiles", "repetitions", "repetition_start",
    "access", "order", "seed", "require_clean", "require_meter",
    "allow_oracle_comparison", "out", "notes",
}


class ExperimentError(Exception):
    """An experiment manifest is malformed or cannot be resumed."""


class _CampaignLock:
    """Non-blocking exclusive lock for one output directory."""

    def __init__(self, path: Path):
        self.path = path
        self._fh: Any = None

    def __enter__(self) -> "_CampaignLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(
                    self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise ExperimentError(
                f"campaign output is already locked: {self.path}") from exc
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._fh.close()
            self._fh = None


@dataclass(frozen=True)
class AgentSpec:
    id: str
    adapter: str
    expected_version: str = ""


@dataclass(frozen=True)
class Experiment:
    path: Path
    name: str
    purpose: str
    primary_metric: str
    tasks_root: Path
    tasks: tuple[str, ...]
    agents: tuple[AgentSpec, ...]
    profiles: tuple[str, ...]
    repetitions: int
    repetition_start: int
    access: str
    order: str
    seed: int
    require_clean: bool
    require_meter: bool
    allow_oracle_comparison: bool
    out: Path | None
    notes: str
    manifest_sha256: str
    raw: dict[str, Any]

    def resolve_out(self, override: str | Path | None = None) -> Path:
        if override is not None:
            return Path(override).expanduser().resolve()
        if self.out is None:
            raise ExperimentError(
                f"{self.path}: no --out given and the manifest has no 'out'")
        return self.out

    def resolve_tasks(self, *, allow_private: bool = False) -> list[Task]:
        try:
            discovered = discover_tasks(
                self.tasks_root, allow_private=allow_private)
        except TaskError as exc:
            raise ExperimentError(f"cannot load tasks_root: {exc}") from exc
        by_id = {task.id: task for task in discovered}
        missing = [task_id for task_id in self.tasks if task_id not in by_id]
        if missing:
            raise ExperimentError(
                f"{self.path}: unknown task id(s): {', '.join(missing)}")
        selected = [by_id[task_id] for task_id in self.tasks]
        for task in selected:
            if task.artifact is None:
                continue
            missing_profiles = [
                profile for profile in self.profiles
                if profile not in task.artifact.profiles
            ]
            if missing_profiles:
                raise ExperimentError(
                    f"{self.path}: task {task.id} does not define profile(s) "
                    f"{', '.join(missing_profiles)}")
        if (len(self.profiles) > 1 and self.access == "oracle"
                and not self.allow_oracle_comparison
                and any(task.artifact is not None for task in selected)):
            raise ExperimentError(
                f"{self.path}: multi-profile binary-recovery campaigns need "
                f"access='binary'; under oracle access the shim is identical "
                f"in every profile. Set allow_oracle_comparison=true only for "
                f"a deliberate black-box control.")
        return selected


@dataclass(frozen=True)
class Cell:
    task_id: str
    profile: str
    agent_id: str
    adapter: str
    repetition: int
    order_index: int

    @property
    def key(self) -> str:
        return f"{self.task_id}|{self.profile}|{self.agent_id}|{self.repetition}"

    @property
    def identity(self) -> tuple[str, str, str, int]:
        return self.task_id, self.profile, self.agent_id, self.repetition


@dataclass
class CampaignResult:
    experiment: Experiment
    out_dir: Path
    records: list[RunRecord]
    cells: list[Cell]
    complete: bool
    resumed: bool


def _canonical(raw: dict[str, Any]) -> bytes:
    return json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _string_list(raw: dict[str, Any], key: str, *, allow_empty: bool = False
                 ) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(
            isinstance(entry, str) and entry for entry in value):
        raise ExperimentError(f"experiment.{key} must be a list of strings")
    if not value and not allow_empty:
        raise ExperimentError(f"experiment.{key} must not be empty")
    if len(set(value)) != len(value):
        raise ExperimentError(f"experiment.{key} contains duplicates")
    return tuple(value)


def _bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ExperimentError(f"experiment.{key} must be boolean")
    return value


def _parse_agents(raw: Any) -> tuple[AgentSpec, ...]:
    if not isinstance(raw, list) or not raw:
        raise ExperimentError("experiment.agents must be a non-empty list")
    agents: list[AgentSpec] = []
    for entry in raw:
        if isinstance(entry, str):
            agents.append(AgentSpec(id=entry, adapter=entry))
            continue
        if not isinstance(entry, dict):
            raise ExperimentError(
                "each experiment.agents entry must be a string or object")
        unknown = set(entry) - {"id", "adapter", "expected_version"}
        if unknown:
            raise ExperimentError(
                f"unknown agent key(s): {', '.join(sorted(unknown))}")
        agent_id = entry.get("id")
        adapter = entry.get("adapter")
        expected = entry.get("expected_version", "")
        if not isinstance(agent_id, str) or not agent_id:
            raise ExperimentError("agent.id must be a non-empty string")
        if "|" in agent_id or "\n" in agent_id or "\r" in agent_id:
            raise ExperimentError(
                "agent.id cannot contain '|' or line breaks")
        if not isinstance(adapter, str) or not adapter:
            raise ExperimentError(
                f"agent {agent_id!r}: adapter must be a non-empty string")
        if not isinstance(expected, str):
            raise ExperimentError(
                f"agent {agent_id!r}: expected_version must be a string")
        agents.append(AgentSpec(
            id=agent_id, adapter=adapter, expected_version=expected))
    ids = [agent.id for agent in agents]
    if len(set(ids)) != len(ids):
        raise ExperimentError("experiment.agents contains duplicate ids")
    return tuple(agents)


def load_experiment(path: str | Path) -> Experiment:
    path = Path(path).resolve()
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes.decode("utf-8"))
    except OSError as exc:
        raise ExperimentError(f"cannot read experiment {path}: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExperimentError(f"{path}: experiment must be a JSON object")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ExperimentError(
            f"{path}: unknown key(s): {', '.join(sorted(unknown))}")
    if raw.get("schema_version") != EXPERIMENT_SCHEMA_VERSION:
        raise ExperimentError(
            f"{path}: schema_version must be {EXPERIMENT_SCHEMA_VERSION}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ExperimentError(f"{path}: name must be a non-empty string")
    purpose = raw.get("purpose")
    if purpose not in PURPOSES:
        raise ExperimentError(
            f"{path}: purpose must be one of {', '.join(PURPOSES)}")
    primary_metric = raw.get("primary_metric")
    if primary_metric not in PRIMARY_METRICS:
        raise ExperimentError(
            f"{path}: primary_metric must be one of "
            f"{', '.join(PRIMARY_METRICS)}")
    tasks_root_raw = raw.get("tasks_root")
    if not isinstance(tasks_root_raw, str) or not tasks_root_raw:
        raise ExperimentError(f"{path}: tasks_root must be a path string")
    tasks_root = (path.parent / tasks_root_raw).resolve()
    tasks = _string_list(raw, "tasks")
    for task_id in tasks:
        if "|" in task_id or "\n" in task_id or "\r" in task_id:
            raise ExperimentError(
                "task ids cannot contain '|' or line breaks")
    profiles = _string_list(raw, "profiles")
    agents = _parse_agents(raw.get("agents"))

    repetitions = raw.get("repetitions")
    if (isinstance(repetitions, bool) or not isinstance(repetitions, int)
            or repetitions < 1):
        raise ExperimentError(f"{path}: repetitions must be a positive int")
    repetition_start = raw.get("repetition_start", 0)
    if (isinstance(repetition_start, bool)
            or not isinstance(repetition_start, int)
            or repetition_start < 0):
        raise ExperimentError(
            f"{path}: repetition_start must be a non-negative int")
    access = raw.get("access")
    if access not in ACCESS_MODES:
        raise ExperimentError(
            f"{path}: access must be one of {', '.join(ACCESS_MODES)}")
    order = raw.get("order", "interleaved")
    if order not in ORDERS:
        raise ExperimentError(
            f"{path}: order must be one of {', '.join(ORDERS)}")
    seed = raw.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ExperimentError(f"{path}: seed must be a non-negative int")
    out_raw = raw.get("out")
    if out_raw is not None and (not isinstance(out_raw, str) or not out_raw):
        raise ExperimentError(f"{path}: out must be a non-empty path string")
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise ExperimentError(f"{path}: notes must be a string")

    return Experiment(
        path=path,
        name=name,
        purpose=purpose,
        primary_metric=primary_metric,
        tasks_root=tasks_root,
        tasks=tasks,
        agents=agents,
        profiles=profiles,
        repetitions=repetitions,
        repetition_start=repetition_start,
        access=access,
        order=order,
        seed=seed,
        require_clean=_bool(raw, "require_clean", True),
        require_meter=_bool(raw, "require_meter", True),
        allow_oracle_comparison=_bool(
            raw, "allow_oracle_comparison", False),
        out=(path.parent / out_raw).resolve() if out_raw else None,
        notes=notes,
        manifest_sha256=hashlib.sha256(_canonical(raw)).hexdigest(),
        raw=raw,
    )


def plan_cells(experiment: Experiment) -> list[Cell]:
    """Expand the matrix with one fresh-adapter cell per repetition."""
    combinations = [
        (task_id, profile, agent)
        for task_id in experiment.tasks
        for profile in experiment.profiles
        for agent in experiment.agents
    ]
    rng = random.Random(experiment.seed)
    planned: list[tuple[str, str, AgentSpec, int]] = []
    if experiment.order == "randomized":
        expanded = [
            (task_id, profile, agent, repetition)
            for repetition in range(
                experiment.repetition_start,
                experiment.repetition_start + experiment.repetitions)
            for task_id, profile, agent in combinations
        ]
        rng.shuffle(expanded)
        planned = expanded
    else:
        for repetition in range(
                experiment.repetition_start,
                experiment.repetition_start + experiment.repetitions):
            block = list(combinations)
            if experiment.order == "interleaved":
                # One full copy of the matrix per repetition, shuffled within
                # the block. Every arm sees the same time window.
                rng.shuffle(block)
            planned.extend(
                (task_id, profile, agent, repetition)
                for task_id, profile, agent in block)
    return [
        Cell(task_id=task_id, profile=profile, agent_id=agent.id,
             adapter=agent.adapter, repetition=repetition,
             order_index=index)
        for index, (task_id, profile, agent, repetition) in enumerate(planned)
    ]


def _read_records(path: Path) -> list[RunRecord]:
    if not path.exists():
        return []
    records: list[RunRecord] = []
    for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            records.append(RunRecord.from_dict(raw))
        except (ValueError, TypeError, KeyError) as exc:
            raise ExperimentError(
                f"{path}:{line_number}: cannot load run row: {exc}") from exc
    return records


def _write_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_text(
        path, json.dumps(state, indent=2, sort_keys=True) + "\n",
        newline="\n")


def _campaign_cell_key(record: RunRecord) -> str:
    value = record.campaign.get("cell_key")
    return value if isinstance(value, str) else ""


def _preflight_agents(
        experiment: Experiment,
        adapter_factory: Callable[[str], Agent]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for spec in experiment.agents:
        try:
            agent = adapter_factory(spec.adapter)
        except AdapterError as exc:
            raise ExperimentError(
                f"adapter preflight failed for {spec.id}: {exc}") from exc
        if agent.name != spec.id:
            raise ExperimentError(
                f"agent id {spec.id!r} does not match adapter.name "
                f"{agent.name!r}")
        version = str(getattr(agent, "version", ""))
        if spec.expected_version and version != spec.expected_version:
            raise ExperimentError(
                f"agent {spec.id}: expected version "
                f"{spec.expected_version!r}, got {version!r}")
        if not version:
            raise ExperimentError(
                f"agent {spec.id}: adapter must expose a non-empty version")
        versions[spec.id] = version
    return versions


def _plugin_for_preflight(explicit: str | None) -> str | None:
    return explicit if explicit is not None else os.environ.get("AEGIS_PLUGIN")


def _check_plugin(plugin: str | None, experiment: Experiment) -> None:
    if not plugin:
        return
    if os.path.sep in plugin or (os.path.altsep and os.path.altsep in plugin):
        if not Path(plugin).is_file():
            raise ExperimentError(
                f"{experiment.path}: plugin does not exist: {plugin}")
    elif shutil.which(plugin) is None:
        raise ExperimentError(
            f"{experiment.path}: plugin executable not found: {plugin}")


def _check_dirty(experiment: Experiment, repo_root: Path) -> None:
    if not experiment.require_clean:
        return
    stamp = environment_stamp(repo_root)
    if stamp.get("commit_dirty") != "no":
        raise ExperimentError(
            f"{experiment.path}: require_clean=true but the repository is "
            f"dirty; commit first or set require_clean=false for a smoke run")


def run_campaign(
        experiment: Experiment,
        *,
        repo_root: Path,
        out_dir: str | Path | None = None,
        allow_private: bool = False,
        cxx: str | None = None,
        plugin: str | None = None,
        clang: str | None = None,
        opt: str | None = None,
        artifact_cache: Path | None = None,
        adapter_timeout: int = 600,
        keep_workspaces: bool = False,
        meter_upstream: str | None = None,
        adapter_factory: Callable[[str], Agent] = create_agent,
        runner_factory: Callable[..., Runner] = Runner,
        ) -> CampaignResult:
    """Run or resume a campaign under an exclusive output-directory lock."""
    out = experiment.resolve_out(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with _CampaignLock(out / ".campaign.lock"):
        return _run_campaign_unlocked(
            experiment,
            repo_root=repo_root,
            out_dir=out,
            allow_private=allow_private,
            cxx=cxx,
            plugin=plugin,
            clang=clang,
            opt=opt,
            artifact_cache=artifact_cache,
            adapter_timeout=adapter_timeout,
            keep_workspaces=keep_workspaces,
            meter_upstream=meter_upstream,
            adapter_factory=adapter_factory,
            runner_factory=runner_factory)


def _run_campaign_unlocked(
        experiment: Experiment,
        *,
        repo_root: Path,
        out_dir: str | Path | None = None,
        allow_private: bool = False,
        cxx: str | None = None,
        plugin: str | None = None,
        clang: str | None = None,
        opt: str | None = None,
        artifact_cache: Path | None = None,
        adapter_timeout: int = 600,
        keep_workspaces: bool = False,
        meter_upstream: str | None = None,
        adapter_factory: Callable[[str], Agent] = create_agent,
        runner_factory: Callable[..., Runner] = Runner,
        ) -> CampaignResult:
    """Run or resume a campaign.

    Every completed row is atomically persisted before the next cell starts.
    A killed process therefore resumes from the last completed cell rather
    than repaying for the whole campaign.
    """
    repo_root = Path(repo_root).resolve()
    out = experiment.resolve_out(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _check_dirty(experiment, repo_root)
    if experiment.require_meter and not meter_upstream:
        raise ExperimentError(
            f"{experiment.path}: require_meter=true but no meter_upstream "
            f"was supplied")

    tasks = experiment.resolve_tasks(allow_private=allow_private)
    task_by_id = {task.id: task for task in tasks}
    cells = plan_cells(experiment)
    cell_by_key = {cell.key: cell for cell in cells}
    if len(cell_by_key) != len(cells):
        raise ExperimentError("campaign plan contains duplicate cell keys")

    plugin_value = _plugin_for_preflight(plugin)
    _check_plugin(plugin_value, experiment)
    if any(
            task.artifact is not None
            and any(task.artifact.profiles[cell.profile].level > 0
                    for cell in cells if cell.task_id == task.id)
            for task in tasks):
        if not plugin_value:
            raise ExperimentError(
                f"{experiment.path}: protected profiles need --plugin or "
                f"AEGIS_PLUGIN before the first paid cell")

    snapshot_path = out / "campaign.json"
    snapshot_text = json.dumps(
        experiment.raw, indent=2, sort_keys=True) + "\n"
    if snapshot_path.exists():
        if snapshot_path.read_text(encoding="utf-8") != snapshot_text:
            raise ExperimentError(
                f"{snapshot_path}: campaign manifest changed after the run "
                f"started; use a new output directory")
    else:
        atomic_write_text(snapshot_path, snapshot_text, newline="\n")

    data_path = out / "aegis-bench.jsonl"
    records = _read_records(data_path)
    completed: dict[str, RunRecord] = {}
    for record in records:
        key = _campaign_cell_key(record)
        if not key:
            raise ExperimentError(
                f"{data_path}: contains a row without campaign.cell_key; "
                f"refusing to mix a standalone run into a campaign")
        if record.campaign.get("manifest_sha256") != experiment.manifest_sha256:
            raise ExperimentError(
                f"{data_path}: row {record.run_id} belongs to a different "
                f"campaign manifest")
        if key not in cell_by_key:
            raise ExperimentError(
                f"{data_path}: row {record.run_id} has unexpected cell {key}")
        if key in completed:
            raise ExperimentError(
                f"{data_path}: duplicate cell {key}; audit the file before "
                f"resuming")
        completed[key] = record

    preflight = _preflight_agents(experiment, adapter_factory)
    state_path = out / "campaign-state.json"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = now
    if state_path.exists():
        try:
            old_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExperimentError(
                f"{state_path}: cannot read campaign state: {exc}") from exc
        if old_state.get("manifest_sha256") != experiment.manifest_sha256:
            raise ExperimentError(
                f"{state_path}: state belongs to a different manifest")
        started = str(old_state.get("started_utc") or now)

    runner = runner_factory(
        repo_root=repo_root, out_dir=out, cxx=cxx, plugin=plugin,
        clang=clang, opt=opt, artifact_cache=artifact_cache,
        adapter_timeout=adapter_timeout, keep_workspaces=keep_workspaces,
        access=experiment.access, meter_upstream=meter_upstream)

    def state(complete: bool) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "campaign": experiment.name,
            "manifest_sha256": experiment.manifest_sha256,
            "started_utc": started,
            "updated_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cells_total": len(cells),
            "cells_completed": len(completed),
            "complete": complete,
            "adapter_versions": preflight,
            "completed_cells": sorted(completed),
        }

    _write_state(state_path, state(False))
    resumed = bool(completed)

    for cell in cells:
        if cell.key in completed:
            continue
        task = task_by_id[cell.task_id]
        try:
            agent = adapter_factory(cell.adapter)
        except AdapterError as exc:
            raise ExperimentError(
                f"cannot create adapter for {cell.key}: {exc}") from exc
        if agent.name != cell.agent_id:
            raise ExperimentError(
                f"adapter identity changed during the campaign: expected "
                f"{cell.agent_id!r}, got {agent.name!r}")
        if str(getattr(agent, "version", "")) != preflight[cell.agent_id]:
            raise ExperimentError(
                f"adapter version changed during the campaign for "
                f"{cell.agent_id!r}")
        record = runner.run(
            [task], [agent], profile=cell.profile,
            repetitions=1, repetition_start=cell.repetition)[0]
        record = replace(record, campaign={
            "id": experiment.name,
            "purpose": experiment.purpose,
            "primary_metric": experiment.primary_metric,
            "manifest_sha256": experiment.manifest_sha256,
            "cell_key": cell.key,
            "order_index": cell.order_index,
        })
        pending = dict(completed)
        pending[cell.key] = record
        reports = write_reports(pending.values(), out)
        completed[cell.key] = record
        _write_state(state_path, state(False))
        status = "PASS" if record.grade.passed else "FAIL"
        print(
            f"[campaign {len(completed)}/{len(cells)}] {status} "
            f"{cell.key} -> {reports['markdown']}",
            flush=True)

    complete = len(completed) == len(cells)
    ordered_records = sorted(
        completed.values(),
        key=lambda record: int(record.campaign.get("order_index", 0)))
    write_reports(ordered_records, out)
    _write_state(state_path, state(complete))
    return CampaignResult(
        experiment=experiment,
        out_dir=out,
        records=ordered_records,
        cells=cells,
        complete=complete,
        resumed=resumed)
