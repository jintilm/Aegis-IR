#!/usr/bin/env python3
"""Differential test runner for Aegis-IR build profiles (stage 3).

Builds the fixture algorithm library under every profile defined in
profiles.json, runs the same input corpus through each binary, and compares
stdout and exit codes against the baseline profile. Property-check and
sanitizer failures in stderr fail the run. A JSON report with binary sizes
and wall-clock times is written for the size/performance baseline.

Usage:
  run.py --plugin build/lib/AegisPass.so [--report build/differential.json]

Environment overrides: CLANG (default clang++-23), OPT (default opt-23).
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

BOUNDARY_LENGTHS = [
    0, 1, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255,
    256, 257, 511, 512, 513, 1023, 1024, 1025,
]

TIMEOUT_SECONDS = 10


def run_cmd(cmd, timeout=TIMEOUT_SECONDS):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def build_profile(name, spec, outdir, clang, opt, plugin):
    """Build one profile. Returns (exe_path, error_string)."""
    outdir.mkdir(parents=True, exist_ok=True)
    flags = spec.get("optflags", ["-O2"])

    lib_ll = outdir / "lib.ll"
    r = run_cmd([clang, *flags, "-S", "-emit-llvm",
                 str(FIXTURES / "algorithm_lib.cpp"),
                 "-I", str(FIXTURES), "-o", str(lib_ll)])
    if r.returncode != 0:
        return None, f"compile library failed:\n{r.stderr.decode(errors='replace')}"

    if spec.get("protect"):
        policy = HERE / spec["policy"]
        protected_ll = outdir / "lib.protected.ll"
        r = run_cmd([opt, f"-load-pass-plugin={plugin}",
                     f"-passes=aegis-policy<policy={policy}>",
                     str(lib_ll), "-S", "-o", str(protected_ll)])
        if r.returncode != 0:
            return None, (f"policy pass failed:\n"
                          f"{r.stderr.decode(errors='replace')}")
        lib_ll = protected_ll

    lib_o = outdir / "lib.o"
    r = run_cmd([clang, *flags, "-c", str(lib_ll), "-o", str(lib_o)])
    if r.returncode != 0:
        return None, f"compile protected IR failed:\n{r.stderr.decode(errors='replace')}"

    driver_o = outdir / "driver.o"
    r = run_cmd([clang, *flags, "-c", str(FIXTURES / "driver.cpp"),
                 "-I", str(FIXTURES), "-o", str(driver_o)])
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
    ap.add_argument("--report", default=None,
                    help="write JSON report to this path")
    ap.add_argument("--keep", action="store_true",
                    help="keep the temporary build directory")
    args = ap.parse_args()

    for tool in (args.clang, args.opt):
        if shutil.which(tool) is None:
            print(f"error: tool not found: {tool}", file=sys.stderr)
            return 2

    profiles = json.loads((HERE / "profiles.json").read_text())["profiles"]
    corpus = build_corpus(args.fuzz_cases, args.seed)
    workdir = Path(tempfile.mkdtemp(prefix="aegis-differential-"))
    failures = []
    report = {"profiles": {}, "corpus_size": len(corpus), "seed": args.seed}

    try:
        exes = {}
        for name, spec in profiles.items():
            exe, err = build_profile(name, spec, workdir / name,
                                     args.clang, args.opt, args.plugin)
            if err:
                failures.append(f"[{name}] {err}")
                continue
            exes[name] = exe
            report["profiles"][name] = {
                "binary_bytes": exe.stat().st_size,
                "cases": 0,
                "total_ms": 0.0,
                "mismatches": 0,
                "sanitizer_or_property_errors": 0,
            }
            print(f"built {name}: {exe.stat().st_size} bytes")

        if "baseline" not in exes:
            print("error: baseline profile failed to build", file=sys.stderr)
            return 1

        baseline_outputs = []
        for idx, payload in enumerate(corpus):
            try:
                out, code, err, ms = execute(exes["baseline"], payload)
            except subprocess.TimeoutExpired:
                failures.append(f"[baseline] timeout on case {idx}")
                baseline_outputs.append(None)
                continue
            baseline_outputs.append((out, code))
            report["profiles"]["baseline"]["cases"] += 1
            report["profiles"]["baseline"]["total_ms"] += ms

        for name, exe in exes.items():
            if name == "baseline":
                continue
            entry = report["profiles"][name]
            for idx, payload in enumerate(corpus):
                expected = baseline_outputs[idx]
                if expected is None:
                    continue
                try:
                    out, code, err, ms = execute(exe, payload)
                except subprocess.TimeoutExpired:
                    failures.append(f"[{name}] timeout on case {idx}")
                    entry["mismatches"] += 1
                    continue
                entry["cases"] += 1
                entry["total_ms"] += ms
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
                        f"[{name}] case {idx}: property/sanitizer report:\n"
                        f"{stderr_text[:1000]}")

        print()
        print(f"{'profile':<16} {'bytes':>8} {'cases':>6} {'ms':>10} "
              f"{'mismatch':>8} {'san-err':>7}")
        for name, entry in report["profiles"].items():
            print(f"{name:<16} {entry['binary_bytes']:>8} "
                  f"{entry['cases']:>6} {entry['total_ms']:>10.1f} "
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