"""Candidate-source policy checks.

The harness grades by execution, but it must not hand a candidate a way to
skip the task. Two classes of shortcut are checked here, before compilation:

* **Reading grader material.** The candidate is compiled with include paths
  that do not contain the task root, but a source that spells out a path
  (``#include "/abs/.../ground_truth/target.cpp"``, ``../../benchmarks``) could
  still try. Absolute and parent-relative quoted includes are rejected, and
  high-signal path fragments are refused outright.
* **Calling out at run time.** The grader runs the candidate with a minimal
  environment and a scratch working directory, but a process can still try to
  exec the probe, spawn shells or open sockets. The checks are a tripwire for
  accidental and lazy oracle replay, not a sandbox.

Limits are deliberately blunt and documented in `docs/benchmark-protocol.md`.
They can only reject; they never change a score that a standalone
implementation would have earned.
"""

from __future__ import annotations

import re
from typing import Iterable

#: Total candidate source bytes accepted. Legitimate solutions to the public
#: tasks are a few KiB; anything near this is an embedded blob.
DEFAULT_MAX_SOURCE_BYTES = 256 * 1024

_FORBIDDEN_FRAGMENTS = (
    "ground_truth",
    "tasks-public",
    "tasks-private",
    "grader/",
    "cases.json",
    "hidden/",
)

_FORBIDDEN_CALLS = re.compile(
    r"\b(system|popen|execl|execle|execlp|execv|execve|execvp|posix_spawn|"
    r"fork|vfork)\s*\(")

_QUOTED_INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.MULTILINE)


def check_candidate(sources: dict[str, str],
                    allowed_headers: Iterable[str] = (),
                    *, max_bytes: int = DEFAULT_MAX_SOURCE_BYTES) -> str:
    """Return a rejection reason, or "" when the sources pass.

    ``allowed_headers`` are bare interface headers the task ships (for
    example ``target.h``); quoted includes are additionally allowed when they
    name a file the candidate itself provides.
    """
    total = 0
    allowed = set(allowed_headers)
    for name, text in sources.items():
        if not isinstance(text, str):
            return f"source '{name}' is not text"
        raw = text.encode("utf-8")
        total += len(raw)
        if total > max_bytes:
            return (f"candidate sources exceed {max_bytes} bytes; embed or "
                    f"wrap of the probe is not a valid solution")

        lowered = text.lower()
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in lowered:
                return (f"source '{name}' references grader material "
                        f"('{fragment}')")

        match = _FORBIDDEN_CALLS.search(text)
        if match:
            return (f"source '{name}' calls '{match.group(1)}'; a submission "
                    f"must be a standalone implementation")

        for include in _QUOTED_INCLUDE.findall(text):
            normalised = include.replace("\\", "/")
            if normalised.startswith("/") or ".." in normalised.split("/"):
                return (f"source '{name}' includes '{include}', which escapes "
                        f"the candidate directory")
            if normalised in allowed or normalised in sources:
                continue
            return (f"source '{name}' includes '{include}', which is not part "
                    f"of the task interface")
    return ""
