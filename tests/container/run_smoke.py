#!/usr/bin/env python3
"""Run one adapter cell in a real local container runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_ROOT = REPO_ROOT / "tools" / "aegis-bench"
sys.path.insert(0, str(BENCH_ROOT))

from aegis_bench.agent import create_agent  # noqa: E402
from aegis_bench.grader import Grade  # noqa: E402
from aegis_bench.runner import Runner  # noqa: E402
from aegis_bench.schema import load_task  # noqa: E402


class _FakeGrader:
    """The smoke tests the boundary, not the already-tested grader."""

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def grade(self, _sources):
        return Grade(True, "ok", "container smoke fake grader", 1, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--image", default="aegis-ir-dev")
    parser.add_argument("--user", default="65534:65534")
    parser.add_argument("--task", default="rolling-token-v1")
    args = parser.parse_args(argv)

    os.environ["AEGIS_CONTAINER_RUNTIME"] = args.runtime
    os.environ["AEGIS_CONTAINER_IMAGE"] = args.image
    os.environ["AEGIS_CONTAINER_USER"] = args.user
    task = load_task(
        REPO_ROOT / "benchmarks" / "tasks-public" / args.task)
    with tempfile.TemporaryDirectory() as tmp:
        with patch("aegis_bench.runner.Grader", _FakeGrader):
            records = Runner(
                repo_root=REPO_ROOT,
                out_dir=Path(tmp),
                adapter_isolation="container",
                enable_tool_broker=False).run(
                    [task], [create_agent("stub")], profile="baseline")
        record = records[0]
        if not record.grade.passed:
            print(record.grade.reason, file=sys.stderr)
            return 1
        container = record.isolation.get("container") or {}
        checks = {
            "adapter": record.isolation.get("adapter") == "container",
            "sandbox": bool(record.isolation.get("sandbox")),
            "network_namespace": bool(
                record.isolation.get("network_namespace")),
            "read_only_root": container.get("read_only_root") is True,
            "network_none": container.get("network") == "none",
            "capabilities_dropped": (
                container.get("capabilities") == "dropped"),
            "no_new_privileges": (
                container.get("no_new_privileges") is True),
            "non_root": container.get("non_root") is True,
        }
        print(json.dumps({
            "checks": checks,
            "isolation": record.isolation,
            "runtime": args.runtime,
            "image": args.image,
        }, indent=2, sort_keys=True))
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
