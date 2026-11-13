"""Aegis-Bench: deterministic engineering checks plus optional model evidence.

The default release path is model-free: differential correctness, `.text`,
p95 and build-time budgets are evaluated by the protection scorecard. External
model adapters remain available for targeted cost studies, but are not needed
for ordinary development or release validation.

Design constraints (see docs/benchmark-protocol.md):

- no network access and no model API keys inside the harness or CI;
- agents are adapters: the harness never embeds a vendor SDK;
- the agent workspace contains only what the task declares as visible; the
  ground truth, hidden cases and grader live outside it.
"""

from .schema import Task, TaskError, load_task
from .agent import Agent, AgentResult, AdapterError
from .audit import AuditReport, audit_path
from .campaign import (
    CampaignResult, Cell, Experiment, ExperimentError, load_experiment,
    plan_cells, run_campaign)
from .grader import Grade, Grader
from .runner import Runner, RunRecord
from .report import write_reports
from .scorecard import evaluate_scorecard, load_budgets, write_scorecard
from .toolbroker import ToolBroker, ToolDenied, ToolError, call_tool
from .worker import ProcessIsolatedAgent, TaskView
from .seccomp import SeccompError, apply_socket_policy

__all__ = [
    "Agent",
    "AgentResult",
    "AdapterError",
    "AuditReport",
    "CampaignResult",
    "Cell",
    "Experiment",
    "ExperimentError",
    "Grade",
    "Grader",
    "RunRecord",
    "Runner",
    "SeccompError",
    "Task",
    "TaskView",
    "TaskError",
    "ToolBroker",
    "ToolDenied",
    "ToolError",
    "ProcessIsolatedAgent",
    "audit_path",
    "apply_socket_policy",
    "call_tool",
    "evaluate_scorecard",
    "load_budgets",
    "load_task",
    "load_experiment",
    "plan_cells",
    "run_campaign",
    "write_reports",
    "write_scorecard",
]

__version__ = "0.3.0-alpha"
