"""Agent adapters shipped with the harness.

Only deterministic, offline adapters live here. Real model adapters are
maintained outside this repository (or injected via entry points) so that
credentials and network access never enter the build, CI, or test paths.

- :class:`ReplayAgent` returns a known candidate (a test double, used to prove
  the grader accepts a correct solution).
- :class:`StubAgent` returns a syntactically valid but semantically empty
  candidate (proves the grader rejects wrong answers).
- :class:`BrokenAgent` raises (proves adapter failures are recorded, not
  crash the run).
"""

from .fake import BrokenAgent, GroundTruthAgent, ReplayAgent, StubAgent

__all__ = ["BrokenAgent", "GroundTruthAgent", "ReplayAgent", "StubAgent"]
