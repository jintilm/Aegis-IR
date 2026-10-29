"""Deterministic offline adapters used by the harness tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent import AdapterError, Agent, AgentResult


class ReplayAgent(Agent):
    """Return a candidate recorded ahead of time.

    This is a *test double*: it stands in for a solver whose answer is already
    known, so grader behaviour can be tested without a model. It reports zero
    fabrication in its ledger: ``tokens`` and ``tool_calls`` are marked
    ``unavailable`` rather than invented.
    """

    name = "replay"
    adversary = "n/a (test double)"

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

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        truth = task.path(task.ground_truth).read_text(encoding="utf-8")
        return AgentResult(
            sources={task.candidate_sources[0]: truth},
            ledger={"tokens": None, "tool_calls": 0,
                    "note": "ground truth replayed; cost is not meaningful"})


class StubAgent(Agent):
    """Return a candidate built from the interface it can see, but wrong.

    The generated code type-checks and links (so failures can only come from
    behaviour), which is what makes it useful as a negative control.
    """

    name = "stub"
    adversary = "n/a (negative control)"

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


class BrokenAgent(Agent):
    name = "broken"
    adversary = "n/a (fault injection)"

    def solve(self, task: Any, workspace: Path) -> AgentResult:
        raise AdapterError("simulated adapter failure")
