"""Deterministic offline adapters used by the harness tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..agent import AdapterError, Agent, AgentResult
from ..toolbroker import BROKER_ENV_URL, ToolError, call_tool


class ReplayAgent(Agent):
    """Return a candidate recorded ahead of time.

    This is a *test double*: it stands in for a solver whose answer is already
    known, so grader behaviour can be tested without a model. It reports zero
    fabrication in its ledger: ``tokens`` and ``tool_calls`` are marked
    ``unavailable`` rather than invented.
    """

    name = "replay"
    adversary = "n/a (test double)"
    version = "builtin-test-double-v1"

    def __init__(self, sources: dict[str, str]):
        self._sources = dict(sources)

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        return AgentResult(
            sources=dict(self._sources),
            ledger={"tokens": None, "tool_calls": 0,
                    "note": "replayed answer; cost is not meaningful"})


class GroundTruthAgent(Agent):
    """Replay the task's own ground truth through the full runner path.

    This exists to validate the *harness*, not to model an attacker: it reads
    a file no real adapter is ever given. It answers "does a known-correct
    solution score 100% end to end, with a report attached?", which is the
    reproducibility check a release needs. It is **not** evidence of anything
    about protection effectiveness, and reports built from it must say so.
    """

    name = "ground-truth-replay"
    adversary = "n/a (harness self-check, not a solver)"
    version = "builtin-test-double-v1"

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        truth = task.path(task.ground_truth).read_text(encoding="utf-8")
        broker_calls = 0
        if os.environ.get(BROKER_ENV_URL):
            try:
                call_tool("list_files", {})
                call_tool("read_file", {"path": task.interface})
                call_tool(
                    "submit_solution",
                    {"source": truth})
                broker_calls = 3
            except ToolError as exc:
                raise AdapterError(
                    f"harness self-check tool broker rejected a request: "
                    f"{exc}") from exc
        return AgentResult(
            sources={task.candidate_sources[0]: truth},
            ledger={"tokens": None, "tool_calls": broker_calls,
                    "tool_broker_calls": broker_calls,
                    "note": "ground truth replayed; cost is not meaningful"})


class StubAgent(Agent):
    """Return a candidate built from the interface it can see, but wrong.

    The generated code type-checks and links (so failures can only come from
    behaviour), which is what makes it useful as a negative control.
    """

    name = "stub"
    adversary = "n/a (negative control)"
    version = "builtin-test-double-v1"

    def __init__(self, body: str | None = None):
        self._body = body or (
            "// negative control: compiles, answers nothing useful\n"
            "#include <cstddef>\n"
            "#include <cstdint>\n"
            "uint64_t bench_hash(const uint8_t *, size_t len) { return len; }\n"
            "uint32_t bench_checksum(const uint8_t *, size_t len) {\n"
            "  return static_cast<uint32_t>(len);\n"
            "}\n"
            "int bench_verify(const uint8_t *, size_t) { return -1; }\n")

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        return AgentResult(
            sources={task.candidate_sources[0]: self._body},
            ledger={"tokens": None, "tool_calls": 1})


class BrokerStubAgent(StubAgent):
    """Negative control that exercises the harness tool broker."""

    name = "broker-stub"

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        calls = 0
        if os.environ.get(BROKER_ENV_URL):
            try:
                call_tool("list_files", {})
                call_tool("read_file", {"path": task.interface})
                call_tool(
                    "submit_solution",
                    {"source": self._body})
                calls = 3
            except ToolError as exc:
                raise AdapterError(
                    f"broker stub rejected: {exc}") from exc
        return AgentResult(
            sources={task.candidate_sources[0]: self._body},
            ledger={"tokens": None, "tool_calls": calls,
                    "tool_broker_calls": calls})


class BrokenAgent(Agent):
    name = "broken"
    adversary = "n/a (fault injection)"
    version = "builtin-test-double-v1"

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        raise AdapterError("simulated adapter failure")


class ProbeQueryAgent(StubAgent):
    """Query the workspace oracle a fixed number of times, then answer badly.

    A deterministic stand-in for an agent that uses the probe as an oracle. It
    exists so the tests can assert that queries are **counted at the broker**
    rather than taken from the adapter's own ledger.
    """

    name = "probe-query"
    adversary = "n/a (oracle accounting test double)"

    def __init__(self, queries: int = 3, body: str | None = None,
                 inputs: list[bytes] | None = None):
        super().__init__(body)
        self.queries = queries
        self.inputs = inputs or [b"aegis-ir", b"", b"x" * 64]

    def _run_shim(self, probe: Path, payload: bytes) -> subprocess.CompletedProcess:
        command = ([sys.executable, str(probe)] if os.name == "nt"
                   else [str(probe)])
        return subprocess.run(command, input=payload, capture_output=True,
                              timeout=60)

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        probe = Path(workspace) / "probe"
        results = []
        for index in range(self.queries):
            payload = self.inputs[index % len(self.inputs)]
            proc = self._run_shim(probe, payload)
            results.append(proc.returncode)
        result = super().solve(task, workspace)
        result.ledger["tool_calls"] = self.queries
        result.ledger["note"] = f"adapter-side shim exit codes: {results}"
        return result
