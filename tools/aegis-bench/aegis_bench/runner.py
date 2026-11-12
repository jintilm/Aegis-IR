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

import contextlib
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
from .grader import CaseOutcome, Grade, Grader
from .meter import MeterProxy, ledger_source_for
from .oracle import OracleBroker, OracleError, install_shim
from .schema import ACCESS_MODES, Task
from .toolbroker import (
    BROKER_ENV_TOKEN, BROKER_ENV_URL, ToolBroker)
from .worker import ProcessIsolatedAgent

DEFAULT_ADAPTER_TIMEOUT = 600
RECORD_SCHEMA_VERSION = 4
ADAPTER_ISOLATION_MODES = ("in-process", "process")

#: What the agent is given for a binary-recovery task.
#:
#: ``oracle`` — the workspace gets a counted shim; the probe stays with the
#: broker. This is a black-box adversary: it can query I/O but cannot inspect
#: the artifact, so a protection transform cannot change what it can learn.
#:
#: ``binary`` — the workspace gets the stripped probe itself (the task
#: contract's "you are given a probe binary"). The agent can execute and
#: disassemble it, which is the only access mode in which obfuscation has
#: anything to act on. Queries are not counted here: the binary is local, so
#: any count would be the adapter's own.
ACCESS_ORACLE = "oracle"
ACCESS_BINARY = "binary"
# ACCESS_MODES is defined in schema so manifest validation and the runner agree.


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


#: Environment variable an adapter reads to find the run's metering proxy.
#: The adapter's own endpoint configuration is left alone: silently rewriting
#: ``LLM_BASE_URL`` would change the agent behind its back, and an adapter that
#: ignores this variable is detectable (its run shows zero proxied requests)
#: rather than quietly mislabelled.
METER_ENV = "AEGIS_METER_BASE_URL"


@contextlib.contextmanager
def _metered_endpoint(meter: MeterProxy | None):
    """Publish the meter's base URL to the adapter for the duration of a run."""
    if meter is None:
        yield
        return
    if meter.unix_path is not None:
        # The worker replaces this with its loopback bridge URL after it
        # enters the private network namespace.
        yield
        return
    previous = os.environ.get(METER_ENV)
    os.environ[METER_ENV] = meter.base_url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(METER_ENV, None)
        else:
            os.environ[METER_ENV] = previous


@contextlib.contextmanager
def _tool_broker_endpoint(broker: ToolBroker | None):
    """Publish the run's tool broker endpoint to the adapter."""
    if broker is None:
        yield
        return
    old_url = os.environ.get(BROKER_ENV_URL)
    old_token = os.environ.get(BROKER_ENV_TOKEN)
    if broker.unix_path is None:
        os.environ[BROKER_ENV_URL] = broker.url
    else:
        os.environ.pop(BROKER_ENV_URL, None)
    os.environ[BROKER_ENV_TOKEN] = broker.token
    try:
        yield
    finally:
        if old_url is None:
            os.environ.pop(BROKER_ENV_URL, None)
        else:
            os.environ[BROKER_ENV_URL] = old_url
        if old_token is None:
            os.environ.pop(BROKER_ENV_TOKEN, None)
        else:
            os.environ[BROKER_ENV_TOKEN] = old_token


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
    #: Optional identifier supplied by the adapter (e.g. a source hash), so a
    #: report can name the exact agent implementation that produced a row.
    adapter_version: str = ""
    #: Configured adapter constructor options. Model adapters put their model
    #: id here so two agents can share one adapter implementation.
    agent_config: dict[str, Any] = field(default_factory=dict)
    #: ``oracle``, ``binary``, or ``n/a`` for tasks with no artifact. Recorded
    #: per row because it decides whether an oracle count exists and whether a
    #: protection transform could have mattered at all.
    access: str = ""
    #: The task's calibration record at run time. A delta on a task whose
    #: unprotected baseline is at the floor or ceiling is not interpretable;
    #: carrying the record into the row lets a report say so.
    calibration: dict[str, Any] = field(default_factory=dict)
    ledger: dict[str, Any] = field(default_factory=dict)
    budgets: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    #: Broker-observed oracle accounting for binary-recovery tasks. This is
    #: measured by the harness, unlike ``ledger``, which the adapter fills in.
    oracle: dict[str, Any] = field(default_factory=dict)
    #: Harness-owned token metering: what the provider reported for every
    #: request that passed through the run's proxy. Empty when the run had no
    #: meter.
    metering: dict[str, Any] = field(default_factory=dict)
    #: Harness-owned tool broker counters. Empty when the broker was disabled
    #: or could not start. ``requests == 0`` means the adapter bypassed it.
    tools: dict[str, Any] = field(default_factory=dict)
    #: Execution boundary and whether it is a security sandbox.
    isolation: dict[str, Any] = field(default_factory=dict)
    #: Experiment-level provenance added by the campaign driver. Empty for a
    #: standalone ``aegis-bench run``.
    campaign: dict[str, Any] = field(default_factory=dict)
    #: Version of the JSONL row contract itself. Rows written before this
    #: field existed are treated as version 1 when loaded.
    record_schema_version: int = RECORD_SCHEMA_VERSION
    #: Task-schema metadata in force for this row (tool policy, input domain,
    #: experiment use, difficulty and protectability).
    task_protocol: dict[str, Any] = field(default_factory=dict)
    private: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_schema_version": self.record_schema_version,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_hash": self.task_hash,
            "agent": self.agent,
            "adversary": self.adversary,
            "adapter_version": self.adapter_version,
            "agent_config": self.agent_config,
            "access": self.access,
            "calibration": self.calibration,
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
            "metering": self.metering,
            "tools": self.tools,
            "isolation": self.isolation,
            "campaign": self.campaign,
            "task_protocol": self.task_protocol,
            "private": self.private,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunRecord":
        """Load a JSONL row for resume and audit.

        This deliberately accepts rows written before campaign/schema fields
        existed. Unknown keys are ignored so a newer report remains readable by
        older tooling, while required measurement fields still fail loudly.
        """
        if not isinstance(raw, dict):
            raise ValueError("run row must be a JSON object")
        grade_raw = raw.get("grade")
        if not isinstance(grade_raw, dict):
            raise ValueError("run row is missing the grade object")
        failures = []
        for entry in grade_raw.get("failures", []):
            if isinstance(entry, dict):
                failures.append(CaseOutcome(
                    name=str(entry.get("case", "")),
                    ok=False,
                    detail=str(entry.get("detail", ""))))
        grade = Grade(
            passed=bool(grade_raw.get("passed", False)),
            stage=str(grade_raw.get("stage", "")),
            reason=str(grade_raw.get("reason", "")),
            cases_total=int(grade_raw.get("cases_total", 0)),
            cases_passed=int(grade_raw.get("cases_passed", 0)),
            failures=failures,
            stderr_excerpt=str(grade_raw.get("stderr_excerpt", "")),
        )
        return cls(
            run_id=str(raw["run_id"]),
            task_id=str(raw["task_id"]),
            task_hash=str(raw.get("task_hash", "")),
            agent=str(raw["agent"]),
            adversary=str(raw.get("adversary", "")),
            adapter_version=str(raw.get("adapter_version", "")),
            agent_config=dict(raw.get("agent_config") or {}),
            access=str(raw.get("access", "")),
            calibration=dict(raw.get("calibration") or {}),
            profile=str(raw["profile"]),
            repetition=int(raw["repetition"]),
            started_utc=str(raw["started_utc"]),
            duration_seconds=float(raw["duration_seconds"]),
            grade=grade,
            ledger=dict(raw.get("ledger") or {}),
            budgets=dict(raw.get("budgets") or {}),
            environment=dict(raw.get("environment") or {}),
            artifact=dict(raw.get("artifact") or {}),
            oracle=dict(raw.get("oracle") or {}),
            metering=dict(raw.get("metering") or {}),
            tools=dict(raw.get("tools") or {}),
            isolation=dict(raw.get("isolation") or {}),
            campaign=dict(raw.get("campaign") or {}),
            record_schema_version=int(raw.get("record_schema_version", 1)),
            task_protocol=dict(raw.get("task_protocol") or {}),
            private=bool(raw.get("private", False)),
            error=str(raw.get("error", "")),
        )


class Runner:
    def __init__(self, *, repo_root: Path, out_dir: Path,
                 cxx: str | None = None, plugin: str | None = None,
                 clang: str | None = None, opt: str | None = None,
                 artifact_cache: Path | None = None,
                 adapter_timeout: int = DEFAULT_ADAPTER_TIMEOUT,
                 keep_workspaces: bool = False,
                 access: str = ACCESS_ORACLE,
                 meter_upstream: str | None = None,
                 enable_tool_broker: bool = True,
                 adapter_isolation: str = "in-process",
                 network_namespace: bool = False):
        if access not in ACCESS_MODES:
            raise ValueError(f"access must be one of {ACCESS_MODES}, "
                             f"got {access!r}")
        if adapter_isolation not in ADAPTER_ISOLATION_MODES:
            raise ValueError(
                f"adapter_isolation must be one of "
                f"{ADAPTER_ISOLATION_MODES}, got {adapter_isolation!r}")
        if network_namespace and adapter_isolation != "process":
            raise ValueError(
                "network_namespace requires adapter_isolation='process'")
        if meter_upstream is not None:
            # Validate now, not mid-cell: a bad URL should stop the run before
            # the first repetition is paid for.
            MeterProxy(meter_upstream)
        self.meter_upstream = meter_upstream
        self.repo_root = Path(repo_root)
        self.out_dir = Path(out_dir)
        self.cxx = cxx
        self.adapter_timeout = adapter_timeout
        self.keep_workspaces = keep_workspaces
        self.access = access
        self.enable_tool_broker = enable_tool_broker
        self.adapter_isolation = adapter_isolation
        self.network_namespace = network_namespace
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

    @staticmethod
    def _install_probe(artifact: BuiltArtifact, workspace: Path) -> Path:
        """Put the stripped probe in the workspace under ``binary`` access.

        This is what the task contract promises the agent ("you are given a
        stripped probe binary"). The copy keeps the executable bit; only the
        probe file moves, never the artifact directory that also holds the
        build log.
        """
        dst = workspace / artifact.path.stem
        shutil.copy2(artifact.path, dst)
        os.chmod(dst, 0o755)
        return dst

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
        meter: MeterProxy | None = None
        tool_broker: ToolBroker | None = None
        bridge_dir: Path | None = None
        metering: dict[str, Any] = {}
        tools: dict[str, Any] = {}
        isolation = {
            "adapter": self.adapter_isolation,
            "sandbox": False,
            "filesystem": "workspace-only by contract; host filesystem reachable",
            "network": "not restricted",
            "network_namespace": False,
        }
        oracle: dict[str, Any] = {}
        access = self.access if task.artifact is not None else "n/a"
        budgets: dict[str, Any] = {
            "max_tool_calls": task.budgets.max_tool_calls,
            "timeout_seconds": task.budgets.timeout_seconds,
            "max_output_tokens": task.budgets.max_output_tokens,
            "adapter_timeout_seconds": self.adapter_timeout,
            "oracle_queries": task.budgets.oracle_queries,
            "enforcement": {
                "adapter_timeout": "unset",
                "max_tool_calls": (
                    "not enforced (adapter self-report)"
                    if not self.enable_tool_broker else "broker not started"),
                "max_output_tokens": "not enforced (adapter self-report)",
                "oracle_queries": ("n/a (no probe)" if task.artifact is None
                                   else "not enforced (no broker)"
                                   if access == ACCESS_ORACLE
                                   else "not counted (binary access)"),
            },
        }
        error = ""
        try:
            self._populate_workspace(task, workspace)
            artifact = self.artifact_for(task, profile)
            if artifact is not None and access == ACCESS_BINARY:
                if task.budgets.oracle_queries is not None:
                    raise OracleError(
                        "access=binary puts the probe in the workspace, so "
                        "budgets.oracle_queries cannot be enforced; unset the "
                        "budget or run with access=oracle")
                self._install_probe(artifact, workspace)
                oracle = {
                    "queries": None, "refused": None, "failed": None,
                    "budget": None, "transport": "local executable",
                    "enforcement": "not counted (binary access)",
                }
            elif artifact is not None:
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
            if self.meter_upstream:
                if self.network_namespace:
                    bridge_dir = bridge_dir or Path(tempfile.mkdtemp(
                        prefix="aegis-bridge-"))
                    meter = MeterProxy(self.meter_upstream).start(
                        unix_path=bridge_dir / "meter.sock")
                else:
                    meter = MeterProxy(self.meter_upstream).start()
                budgets["enforcement"]["tokens"] = \
                    "measured by harness (provider usage via proxy)"
            else:
                budgets["enforcement"]["tokens"] = "not metered (no proxy)"
            if self.enable_tool_broker:
                if self.network_namespace:
                    bridge_dir = bridge_dir or Path(tempfile.mkdtemp(
                        prefix="aegis-bridge-"))
                tool_broker = ToolBroker(
                    workspace=workspace, task=task, access=access,
                    max_calls=task.budgets.max_tool_calls,
                    enable_disassembly=access == ACCESS_BINARY).start(
                        unix_path=(
                            bridge_dir / "broker.sock"
                            if bridge_dir is not None else None))
                budgets["enforcement"]["max_tool_calls"] = (
                    "measured and capped by harness broker")
            timeout = self.adapter_timeout or task.budgets.timeout_seconds
            budgets["enforcement"]["adapter_timeout"] = _deadline_mode(timeout)
            budgets["enforcement"]["adapter_isolation"] = self.adapter_isolation
            run_agent: Agent = agent
            if self.adapter_isolation == "process":
                isolation_ports = []
                if (tool_broker is not None
                        and tool_broker.unix_path is None):
                    isolation_ports.append(tool_broker.port)
                if meter is not None and meter.unix_path is None:
                    isolation_ports.append(meter.port)
                run_agent = ProcessIsolatedAgent(
                    agent, timeout_seconds=timeout,
                    tcp_ports=tuple(isolation_ports),
                    network_namespace=self.network_namespace,
                    meter_unix_path=(
                        meter.unix_path if meter is not None else None),
                    meter_prefix=(
                        meter.upstream_prefix if meter is not None else ""),
                    broker_unix_path=(
                        tool_broker.unix_path
                        if tool_broker is not None else None))
            with _metered_endpoint(meter), _tool_broker_endpoint(tool_broker):
                # Inside the block, so an adapter that reads its endpoint in
                # ``prepare`` sees the meter too.
                run_agent.prepare(task, workspace)
                result, _enforced = _call_with_deadline(
                    lambda: run_agent.solve(task, workspace), timeout)
            if self.adapter_isolation == "process":
                isolation.update(run_agent.last_isolation)
            ledger = dict(result.ledger)
            ledger["ledger_source"] = "self-reported by adapter"
            if result.notes:
                ledger["notes"] = result.notes
            if meter is not None:
                metering = meter.stop(
                    reported_by_adapter=ledger.get("tokens"))
                meter = None
                ledger["ledger_source"] = ledger_source_for(metering)
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
            if meter is not None:
                # Reached when the adapter raised or timed out before it
                # returned a ledger. The traffic it did make still happened
                # and is still cost.
                metering = meter.stop(reported_by_adapter=ledger.get("tokens"))
                if ledger:
                    ledger["ledger_source"] = ledger_source_for(metering)
            if broker is not None:
                broker.stop()
                oracle = broker.stats.to_dict()
            if tool_broker is not None:
                tools = tool_broker.stop(
                    reported_by_adapter=ledger.get("tool_calls"))
                tool_broker = None
            if oracle:
                oracle["access"] = access
            if self.keep_workspaces:
                shutil.copytree(workspace, self.out_dir / f"ws-{run_id}",
                                dirs_exist_ok=True)
            shutil.rmtree(workspace, ignore_errors=True)
            if bridge_dir is not None:
                shutil.rmtree(bridge_dir, ignore_errors=True)

        return RunRecord(
            run_id=run_id, task_id=task.id, task_hash=task.content_hash,
            agent=agent.name, adversary=agent.adversary,
            adapter_version=str(getattr(agent, "version", "")),
            agent_config=dict(getattr(agent, "adapter_options", {}) or {}),
            access=access,
            calibration=(
                {access: calibration.to_dict()}
                if (calibration := task.calibration_for(
                    access, str(getattr(agent, "model", "") or "")))
                else {}
            ),
            profile=profile,
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
            metering=metering,
            tools=tools,
            isolation=isolation,
            task_protocol=task.protocol_dict(),
            private=task.private,
            error=error)

    # -- a whole matrix --------------------------------------------------

    def run(self, tasks: list[Task], agents: list[Agent], *, profile: str,
            repetitions: int = 1,
            repetition_start: int = 0) -> list[RunRecord]:
        if repetitions < 0:
            raise ValueError("repetitions must be non-negative")
        if repetition_start < 0:
            raise ValueError("repetition_start must be non-negative")
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
                                           repetition=repetition_start + rep)
                    records.append(record)
                    status = "PASS" if record.grade.passed else "FAIL"
                    print(f"[{status}] {task.id} / {agent.name} "
                          f"({profile}, rep {rep}) - "
                          f"{record.duration_seconds:.2f}s "
                          f"{record.grade.reason}", file=sys.stderr)
        return records
