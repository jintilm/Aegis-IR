"""Command-line entry point for Aegis-Bench.

    python -m aegis_bench hash  <task-dir>
    python -m aegis_bench check <task-dir>... [--tasks-root DIR]
    python -m aegis_bench run   --tasks-root DIR --profile NAME [options]

``run`` requires an adapter chosen by ``--adapter``. Only offline adapters
ship in this repository; a real-model adapter is passed as
``module:Class`` from outside the tree, which keeps credentials and network
access out of the repo and out of CI.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from .schema import TaskError, discover_tasks, load_task
from .agent import Agent, AdapterError
from .artifact import ArtifactError
from .runner import ACCESS_MODES, ACCESS_ORACLE, Runner
from .report import write_reports


def _repo_root() -> Path:
    # .../aegis-ir/tools/aegis-bench/aegis_bench/cli.py
    return Path(__file__).resolve().parents[3]


def _adapter(spec: str) -> Agent:
    """Resolve ``module:Class`` (or a built-in short name) to an adapter."""
    builtins = {
        "stub": "aegis_bench.adapters.fake:StubAgent",
        "broken": "aegis_bench.adapters.fake:BrokenAgent",
        "ground-truth": "aegis_bench.adapters.fake:GroundTruthAgent",
        "probe-query": "aegis_bench.adapters.fake:ProbeQueryAgent",
    }
    spec = builtins.get(spec, spec)
    if ":" not in spec:
        raise AdapterError(f"adapter must be 'module:Class', got {spec!r}")
    module_name, class_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not issubclass(cls, Agent):
        raise AdapterError(f"{spec} is not an Agent subclass")
    return cls()


def cmd_hash(args: argparse.Namespace) -> int:
    task = load_task(args.task_dir, verify_hash=False)
    task_path = task.root / "task.json"
    raw = json.loads(task_path.read_text(encoding="utf-8"))
    raw["content_hash"] = task.computed_hash()
    task_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    print(f"{task.id}: {raw['content_hash']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    dirs = [Path(d) for d in args.task_dir]
    if args.tasks_root:
        dirs += [t.root for t in discover_tasks(
            args.tasks_root, verify_hash=False,
            allow_private=args.allow_private)]
    if not dirs:
        print("error: no tasks given", file=sys.stderr)
        return 2
    failures = 0
    for d in dirs:
        try:
            task = load_task(d, allow_private=args.allow_private)
        except TaskError as exc:
            failures += 1
            print(f"FAIL {d}: {exc}", file=sys.stderr)
            continue
        print(f"OK   {task.id} ({task.content_hash[:19]}, "
              f"{task.task_type}, {len(task.hidden_cases)} hidden file(s), "
              f"fuzz={task.fuzz.cases}"
              + (f", profiles={','.join(sorted(task.artifact.profiles))}"
                 if task.artifact else "") + ")")
    return 1 if failures else 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        tasks = discover_tasks(args.tasks_root,
                               allow_private=args.allow_private)
        agent = _adapter(args.adapter)
    except (TaskError, AdapterError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.task:
        tasks = [t for t in tasks if t.id in set(args.task)]
        if not tasks:
            print("error: no matching tasks", file=sys.stderr)
            return 2

    runner = Runner(repo_root=_repo_root(), out_dir=Path(args.out),
                    cxx=args.cxx, plugin=args.plugin, clang=args.clang,
                    opt=args.opt, artifact_cache=args.artifact_cache,
                    adapter_timeout=args.adapter_timeout,
                    keep_workspaces=args.keep_workspaces,
                    access=args.access,
                    meter_upstream=args.meter_upstream)
    try:
        records = runner.run(tasks, [agent], profile=args.profile,
                             repetitions=args.repetitions)
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    paths = write_reports(records, Path(args.out))
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0 if all(r.grade.passed for r in records) else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aegis-bench")
    sub = ap.add_subparsers(dest="command", required=True)

    p_hash = sub.add_parser("hash", help="record a task's content hash")
    p_hash.add_argument("task_dir")
    p_hash.set_defaults(func=cmd_hash)

    p_check = sub.add_parser("check", help="validate task manifests")
    p_check.add_argument("task_dir", nargs="*")
    p_check.add_argument("--tasks-root")
    p_check.add_argument("--allow-private", action="store_true",
                         help="load tasks marked private")
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="run an adapter over tasks")
    p_run.add_argument("--tasks-root", required=True)
    p_run.add_argument("--adapter", required=True,
                       help="'module:Class' or a built-in (stub, broken)")
    p_run.add_argument("--profile", required=True,
                       help="build profile label, e.g. baseline/release")
    p_run.add_argument("--task", action="append", default=[],
                       help="restrict to a task id (repeatable)")
    p_run.add_argument("--allow-private", action="store_true",
                       help="run tasks marked private (never publish results)")
    p_run.add_argument("--repetitions", type=int, default=1)
    p_run.add_argument("--out", default="bench-out")
    p_run.add_argument("--cxx", default=None)
    p_run.add_argument("--clang", default=None,
                       help="C++ frontend for probe builds "
                            "(default: $BENCH_CLANG or clang++-23)")
    p_run.add_argument("--opt", default=None,
                       help="LLVM opt for probe builds "
                            "(default: $BENCH_OPT or opt-23)")
    p_run.add_argument("--plugin", default=None,
                       help="AegisPass plugin for level>=1 artifact profiles "
                            "(default: $AEGIS_PLUGIN)")
    p_run.add_argument("--artifact-cache", default=None,
                       help="directory for built probes (default: "
                            "<out>/.artifacts)")
    p_run.add_argument("--adapter-timeout", type=int, default=600,
                       help="wall-clock seconds per adapter.solve call "
                            "(0 disables; default 600)")
    p_run.add_argument("--access", choices=list(ACCESS_MODES),
                       default=ACCESS_ORACLE,
                       help="what a binary-recovery workspace gets: 'oracle' "
                            "(counted shim; black-box) or 'binary' (the "
                            "stripped probe itself; queries uncounted). "
                            "Default: oracle")
    p_run.add_argument("--meter-upstream", default=None, metavar="URL",
                       help="start a loopback metering proxy in front of this "
                            "model endpoint and export it to the adapter as "
                            "AEGIS_METER_BASE_URL; token counts then come from "
                            "the provider's usage report instead of the "
                            "adapter's own arithmetic")
    p_run.add_argument("--keep-workspaces", action="store_true")
    p_run.set_defaults(func=cmd_run)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
