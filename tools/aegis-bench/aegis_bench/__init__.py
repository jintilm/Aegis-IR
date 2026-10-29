"""Aegis-Bench: a reproducible benchmark for AI-assisted reverse engineering.

The harness measures the *cost* an agent pays (tokens, tool calls, wall clock)
to reach a fixed success criterion, and whether it reaches it at all. Scores
come from executing the candidate against hidden property tests and a
differential fuzz corpus, never from text similarity.

Design constraints (see docs/benchmark-protocol.md):

- no network access and no model API keys inside the harness or CI;
- agents are adapters: the harness never embeds a vendor SDK;
- the agent workspace contains only what the task declares as visible; the
  ground truth, hidden cases and grader live outside it.
"""

from .schema import Task, TaskError, load_task
from .agent import Agent, AgentResult, AdapterError
from .grader import Grade, Grader
from .runner import Runner, RunRecord
from .report import write_reports

__all__ = [
    "Agent",
    "AgentResult",
    "AdapterError",
    "Grade",
    "Grader",
    "RunRecord",
    "Runner",
    "Task",
    "TaskError",
    "load_task",
    "write_reports",
]

__version__ = "0.1.0-alpha"
