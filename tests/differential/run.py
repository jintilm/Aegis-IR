#!/usr/bin/env python3
"""Differential test runner for Aegis-IR build profiles (stage 3, extended in
stage 4).

Builds the fixture algorithm library under every profile defined in
profiles.json, runs the same input corpus through each binary, and compares
stdout and exit codes against the baseline profile. Property-check and
sanitizer failures in stderr fail the run. A JSON report with binary sizes,
build times and wall-clock times is written for the engineering scorecard.

Protected profiles run the full Aegis pipeline in one opt invocation:
  aegis-policy<policy=...>,aegis-decoys,default<O2>,aegis-verify
so a build whose decoys the optimizer erased fails here, not in production.

Usage:
  run.py --plugin build/lib/AegisPass.so [--report build/differential.json]

Environment overrides: CLANG (default clang++-23), OPT (default opt-23).
"""

import argparse
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FIXTURES = HERE / "fixtures"
DEFAULT_PROFILES = HERE / "profiles.json"

BOUNDARY_LENGTHS = [
    0, 1, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255,
    256, 257, 511, 512, 513, 1023, 1024, 1025,
]

TIMEOUT_SECONDS = 10
RUNTIME_ROUNDS = 3


def run_cmd(cmd, timeout=TIMEOUT_SECONDS):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def build_profile(name, spec, outdir, fixture_dir, config_dir,
                  clang, opt, plugin):
    """Build one profile. Returns (exe_path, error_string)."""
    outdir.mkdir(parents=True, exist_ok=True)
    flags = spec.get("optflags", ["-O2"])

    lib_ll = outdir / "lib.ll"
    src_flags = list(flags)
    pipeline = spec.get("pipeline")
    if pipeline:
        # The Aegis passes must see frontend IR: a -O2 -emit-llvm module has
        # already been inlined, so guarding a function there protects a dead
        # copy. default<O2> runs inside the opt pipeline instead.
        src_flags += ["-Xclang", "-disable-llvm-passes"]
    r = run_cmd([clang, *src_flags, "-S", "-emit-llvm",
                 str(fixture_dir / "algorithm_lib.cpp"),
                 "-I", str(fixture_dir), "-o", str(lib_ll)])
    if r.returncode != 0:
        return None, f"compile library failed:\n{r.stderr.decode(errors='replace')}"

    pipeline = spec.get("pipeline")
    if pipeline:
        # Relative policy paths are resolved against this directory so the
        # profile file stays location-independent.
        policy = config_dir / spec["policy"] if spec.get("policy") else None
        passes = pipeline.format(policy=policy) if policy else pipeline
        protected_ll = outdir / "lib.protected.ll"
        r = run_cmd([opt, f"-load-pass-plugin={plugin}",
                     f"-passes={passes}",
                     str(lib_ll), "-S", "-o", str(protected_ll)])
        if r.returncode != 0:
            return None, (f"aegis pipeline failed ({passes}):\n"
                          f"{r.stderr.decode(errors='replace')}")
        lib_ll = protected_ll

    lib_o = outdir / "lib.o"
    r = run_cmd([clang, *flags, "-c", str(lib_ll), "-o", str(lib_o)])
    if r.returncode != 0:
        return None, f"compile protected IR failed:\n{r.stderr.decode(errors='replace')}"

    driver_o = outdir / "driver.o"
    r = run_cmd([clang, *flags, "-c", str(fixture_dir / "driver.cpp"),
                 "-I", str(fixture_dir), "-o", str(driver_o)])
    if r.returncode != 0:
        return None, f"compile driver failed:\n{r.stderr.decode(errors='replace')}"

    exe = outdir / ("prog.exe" if os.name == "nt" else "prog")
    link = [clang, *flags]
    if spec.get("strip"):
        link.append("-s")
    link += [str(lib_o), str(driver_o), "-o", str(exe)]
    r = run_cmd(link)
    if r.returncode != 0:
        return None, f"link failed:\n{r.stderr.decode(errors='replace')}"
    return exe, None


def percentile(samples, pct):
    """Nearest-rank percentile. Empty input yields 0.0."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(0, min(len(ordered) - 1,
                      math.ceil(pct / 100.0 * len(ordered)) - 1))
    return ordered[rank]


def runtime_metrics(case_timings, baseline_name, rounds):
    """Paired per-case means, with an explicit baseline and complete rounds."""
    baseline = case_timings[baseline_name]
    result = {}
    for name, timings in case_timings.items():
        ratios = []
        for base_samples, samples in zip(baseline, timings):
            if len(base_samples) != rounds or len(samples) != rounds:
                continue
            base_ms = statistics.mean(base_samples)
            if base_ms > 0:
                ratios.append(statistics.mean(samples) / base_ms)
        complete = len(ratios) == len(baseline) == len(timings) and bool(ratios)
        ratio_p95 = percentile(ratios, 95) if complete else None
        result[name] = {
            "case_timings_ms": timings,
            "runtime_pairs": len(ratios),
            "runtime_ratio_p95": ratio_p95,
            "relative_p95_delta_pct": (
                (ratio_p95 - 1.0) * 100.0 if ratio_p95 is not None else None),
        }
    return result


def section_sizes(exe):
    """Return {text, data, bss} in bytes, or {} when `size` is unavailable.

    File size alone is page-quantised and hides small deltas, so the report
    records the ELF section totals the linker actually produced.
    """
    try:
        r = subprocess.run(["size", str(exe)], capture_output=True,
                           timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    lines = r.stdout.decode(errors="replace").strip().splitlines()
    if len(lines) < 2:
        return {}
    fields = lines[1].split()
    if len(fields) < 3:
        return {}
    try:
        text, data, bss = (int(f) for f in fields[:3])
    except ValueError:
        return {}
    return {"text": text, "data": data, "bss": bss}


def build_corpus(fuzz_cases, seed):
    """Deterministic corpus: fixed cases, boundary lengths, seeded fuzz."""
    corpus = [
        b"",
        b"\x00",
        b"aegis-ir",
        bytes(range(256)),
        b"\x00" * 64,
        b"\xff" * 64,
        b"A" * 7,
        b"A" * 8,
        b"A" * 9,
    ]
    for length in BOUNDARY_LENGTHS:
        corpus.append(bytes((i * 31 + 7) & 0xFF for i in range(length)))
    rnd = random.Random(seed)
    for _ in range(fuzz_cases):
        length = rnd.randrange(0, 2049)
        corpus.append(bytes(rnd.randrange(256) for _ in range(length)))
    return corpus


def execute(exe, payload):
    """Run one case. Returns (stdout, exit_code, stderr, elapsed_ms) or raises."""
    start = time.perf_counter()
    r = subprocess.run([str(exe)], input=payload, capture_output=True,
                       timeout=TIMEOUT_SECONDS)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return r.stdout, r.returncode, r.stderr, elapsed_ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", required=True, help="path to AegisPass library")
    ap.add_argument("--clang", default=os.environ.get("CLANG", "clang++-23"))
    ap.add_argument("--opt", default=os.environ.get("OPT", "opt-23"))
    ap.add_argument("--fuzz-cases", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--build-samples", type=int, default=3,
                    help="independent cold builds per profile (default: 3)")
    ap.add_argument("--fixture-dir", default=str(DEFAULT_FIXTURES),
                    help="directory containing algorithm_lib.cpp and driver.cpp")
    ap.add_argument("--profiles", default=str(DEFAULT_PROFILES),
                    help="profile matrix JSON; relative policies resolve "
                         "against its directory")
    ap.add_argument("--runtime-baseline", default=None,
                    help="performance baseline (default: profile manifest's "
                         "runtime_baseline_profile, otherwise baseline)")
    ap.add_argument("--report", default=None,
                    help="write JSON report to this path")
    ap.add_argument("--keep", action="store_true",
                    help="keep the temporary build directory")
    args = ap.parse_args()

    for tool in (args.clang, args.opt):
        if shutil.which(tool) is None:
            print(f"error: tool not found: {tool}", file=sys.stderr)
            return 2
    if args.build_samples < 1:
        print("error: --build-samples must be at least 1", file=sys.stderr)
        return 2

    fixture_dir = Path(args.fixture_dir).resolve()
    profiles_path = Path(args.profiles).resolve()
    config_dir = profiles_path.parent
    for path in (fixture_dir, profiles_path):
        if not path.exists():
            print(f"error: path not found: {path}", file=sys.stderr)
            return 2
    profile_config = json.loads(profiles_path.read_text())
    profiles = profile_config["profiles"]
    runtime_baseline = args.runtime_baseline or profile_config.get(
        "runtime_baseline_profile", "baseline")
    if runtime_baseline not in profiles:
        print(f"error: runtime baseline {runtime_baseline!r} is missing", file=sys.stderr)
        return 2
    corpus = build_corpus(args.fuzz_cases, args.seed)
    workdir = Path(tempfile.mkdtemp(prefix="aegis-differential-"))
    failures = []
    report = {
        "fixture": fixture_dir.name,
        "fixture_dir": str(fixture_dir),
        "profiles_source": str(profiles_path),
        "build_samples_required": args.build_samples,
        "build_sample_order": "profile-interleaved",
        "profiles": {},
        "corpus_size": len(corpus),
        "seed": args.seed,
        "correctness_baseline_profile": "baseline",
        "runtime_baseline_profile": runtime_baseline,
    }

    try:
        exes = {}
        build_samples_ms = {name: [] for name in profiles}
        failed_profiles = set()
        # Build one sample of every profile per round. Building all three
        # baseline samples before touching the protected profiles lets host
        # load, disk cache and compiler warm-up masquerade as transform cost.
        for sample_index in range(args.build_samples):
            for name, spec in profiles.items():
                if name in failed_profiles:
                    continue
                build_started = time.perf_counter()
                sample_exe, err = build_profile(
                    name, spec,
                    workdir / name / f"sample-{sample_index:02d}",
                    fixture_dir, config_dir, args.clang, args.opt,
                    args.plugin)
                build_samples_ms[name].append(
                    (time.perf_counter() - build_started) * 1000.0)
                if err:
                    failures.append(
                        f"[{name}] build sample {sample_index + 1}/"
                        f"{args.build_samples}: {err}")
                    failed_profiles.add(name)
                    exes.pop(name, None)
                    continue
                exes.setdefault(name, sample_exe)

        for name, spec in profiles.items():
            if name in failed_profiles or name not in exes:
                continue
            exe = exes[name]
            samples = build_samples_ms[name]
            sections = section_sizes(exe)
            build_median_ms = statistics.median(samples)
            report["profiles"][name] = {
                "binary_bytes": exe.stat().st_size,
                "sections": sections,
                "pipeline": spec.get("pipeline"),
                "build_samples_ms": samples,
                "build_median_ms": build_median_ms,
                "build_ms": build_median_ms,
                "cases": 0,
                "total_ms": 0.0,
                "timings_ms": [],
                "mismatches": 0,
                "sanitizer_or_property_errors": 0,
            }
            print(f"built {name}: {exe.stat().st_size} bytes, "
                  f"median build {build_median_ms:.1f} ms "
                  f"({len(samples)} samples)")

        if "baseline" not in exes or runtime_baseline not in exes:
            print("error: correctness or runtime baseline failed to build", file=sys.stderr)
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            return 1

        # Interleave profiles per case and repeat the timing pass. The corpus
        # consists of short-lived processes, so running one profile after
        # another lets host drift and CPU scheduling masquerade as protection
        # overhead. Correctness is compared on the first pass; the timing
        # score is the p95 of per-case protected/baseline ratios across the
        # repeated passes.
        order = ["baseline", *[name for name in exes if name != "baseline"]]
        case_timings = {
            name: [[]
                   for _ in corpus]
            for name in exes
        }
        report["runtime_rounds"] = RUNTIME_ROUNDS
        for round_index in range(RUNTIME_ROUNDS):
            for idx, payload in enumerate(corpus):
                expected = None
                for name in order:
                    exe = exes[name]
                    entry = report["profiles"][name]
                    try:
                        out, code, err, ms = execute(exe, payload)
                    except subprocess.TimeoutExpired:
                        failures.append(
                            f"[{name}] timeout on case {idx}")
                        if round_index == 0:
                            entry["mismatches"] += 1
                        continue
                    case_timings[name][idx].append(ms)
                    if round_index == 0:
                        entry["cases"] += 1
                        entry["total_ms"] += ms
                        entry["timings_ms"].append(ms)
                    if name == "baseline":
                        expected = (out, code)
                        continue
                    if expected is None:
                        continue
                    if round_index == 0:
                        if (out, code) != expected:
                            entry["mismatches"] += 1
                            failures.append(
                                f"[{name}] case {idx}: output/exit mismatch "
                                f"(expected {expected[1]}, got {code})")
                        stderr_text = err.decode(errors="replace")
                        if "PROPERTY FAIL" in stderr_text or \
                                "ERROR: AddressSanitizer" in stderr_text or \
                                "runtime error:" in stderr_text:
                            entry["sanitizer_or_property_errors"] += 1
                            failures.append(
                                f"[{name}] case {idx}: "
                                f"property/sanitizer report:\n"
                                f"{stderr_text[:1000]}")

        print()
        for entry in report["profiles"].values():
            entry["p95_ms"] = percentile(entry.pop("timings_ms"), 95)
        for name, metrics in runtime_metrics(
                case_timings, runtime_baseline, RUNTIME_ROUNDS).items():
            report["profiles"][name].update(metrics)
        print(f"{'profile':<16} {'bytes':>8} {'text':>7} {'data':>6} "
              f"{'buildms':>9} {'p95ms':>9} {'relp95':>8} "
              f"{'cases':>6} {'mismatch':>8} {'san-err':>7}")
        for name, entry in report["profiles"].items():
            sec = entry.get("sections") or {}
            p95 = entry["p95_ms"]
            delta = entry["relative_p95_delta_pct"]
            delta_text = f"{delta:7.2f}%" if delta is not None else "     n/a"
            print(f"{name:<16} {entry['binary_bytes']:>8} "
                  f"{sec.get('text', 0):>7} {sec.get('data', 0):>6} "
                  f"{entry['build_ms']:>9.1f} {p95:>9.2f} "
                  f"{delta_text} "
                  f"{entry['cases']:>6} "
                  f"{entry['mismatches']:>8} "
                  f"{entry['sanitizer_or_property_errors']:>7}")

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            print(f"\nreport written to {report_path}")
    finally:
        if args.keep:
            print(f"workdir kept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for f in failures[:50]:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("\ndifferential tests: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
