"""Agent adapters.

An adapter receives a task's *visible* workspace and a budget, and returns a
candidate implementation. The harness stays vendor-neutral: adapters may wrap
an LLM, a static tool, or a human-driven session, but they must not need
network access or credentials at import time.

The adapter contract deliberately has no channel back into the grader. An
adapter's return value is data (source text + a self-reported ledger); the
grader never trusts it beyond "this is the candidate source".
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AdapterError(Exception):
    """The adapter failed to produce a candidate (crash, budget, config)."""


@dataclass
class AgentResult:
    """What an adapter returns for one task attempt.

    ``sources`` maps a bare filename to its text content. The runner writes
    these into a fresh directory; nothing else from the adapter is executed.
    ``ledger`` carries cost accounting (tokens, tool calls, wall clock) as the
    adapter measured it. The runner records it verbatim and marks whether the
    harness could independently corroborate any of it — today it cannot, so
    self-reported numbers are labelled as such in reports.
    """

    sources: dict[str, str]
    ledger: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


class Agent(abc.ABC):
    """Base class for adapters."""

    #: Short stable identifier used in result rows, e.g. "fake", "c1-static".
    name: str = "agent"

    #: Human-readable description of the attacker this adapter models; must
    #: name a threat-model class (C0-C4) or the white-box control.
    adversary: str = "unspecified"

    def prepare(self, task: Any, workspace: Path) -> None:
        """Called once before ``solve``; workspace is the visible-only copy."""

    @abc.abstractmethod
    def solve(self, task: Any, workspace: Path) -> AgentResult:
        """Produce a candidate for ``task``, reading only ``workspace``."""
