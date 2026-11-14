#!/usr/bin/env python3
"""Run the Aegis differential matrix over a pinned external C workload.

This optional smoke test fetches ``kokke/tiny-AES-c`` at one immutable commit,
wraps its AES-128 ECB implementation in the fixture interface expected by
``tests/differential/run.py``, and checks that the protected profiles preserve
behaviour. It is deliberately outside CTest and CI: those paths stay
network-free.

The upstream source is not copied into this repository. Use:

    python3 tests/external/run_tiny_aes.py \
      --plugin build/lib/AegisPass.so \
      --report build/tiny-aes-external-report.json \
      --markdown build/tiny-aes-external-report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_URL = "https://github.com/kokke/tiny-AES-c.git"
COMMIT = "23856752fbd139da0b8ca6e471a13d5bcc99a08d"
LICENSE = "Unlicense"
REPO_ROOT = Path(__file__).resolve().parents[2]
DIFFERENTIAL = REPO_ROOT / "tests" / "differential" / "run.py"

ALGORITHM_LIB = r"""
#define CBC 0
#define CTR 0
#define ECB 1
#include "aes.c"

#include <cstring>

extern "C" __attribute__((noinline, used))
void aegis_external_aes_block(const uint8_t *input, uint8_t *output) {
  static const uint8_t key[16] = {
      0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
      0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c};
  struct AES_ctx context;
  AES_init_ctx(&context, key);
  std::memcpy(output, input, AES_BLOCKLEN);
  AES_ECB_encrypt(&context, output);
}
"""

DRIVER = r"""
#include <cstdint>
#include <cstdio>
#include <vector>

extern "C" void aegis_external_aes_block(const std::uint8_t *input,
                                         std::uint8_t *output);

int main() {
  std::vector<std::uint8_t> input;
  std::uint8_t buffer[4096];
  std::size_t read = 0;
  while ((read = std::fread(buffer, 1, sizeof(buffer), stdin)) > 0)
    input.insert(input.end(), buffer, buffer + read);

  std::uint8_t block[16] = {};
  std::uint64_t state = 0x9e3779b97f4a7c15ULL ^ input.size();
  for (std::size_t i = 0; i < sizeof(block); ++i) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    const std::uint8_t mixed = static_cast<std::uint8_t>(state >> 24);
    block[i] = static_cast<std::uint8_t>(
        (input.empty() ? mixed : input[i % input.size()]) ^ mixed);
  }

  std::uint8_t output[16] = {};
  aegis_external_aes_block(block, output);

  std::uint64_t digest = 0xcbf29ce484222325ULL;
  for (std::uint8_t byte : output) {
    digest ^= byte;
    digest *= 0x100000001b3ULL;
  }
  std::printf("input=%zu cipher=", input.size());
  for (std::uint8_t byte : output)
    std::printf("%02x", byte);
  std::printf(" digest=%llu\n",
              static_cast<unsigned long long>(digest));
  return 0;
}
"""


def run(command: list[str], *, cwd: Path | None = None,
        timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({' '.join(command)}):\n"
            f"{result.stdout}{result.stderr}")
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def benchmark_environment() -> dict[str, str]:
    commit = run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
    dirty = run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout.strip()
    return {"commit": commit, "commit_dirty": "yes" if dirty else "no"}


def checkout(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q"], cwd=destination)
    run(["git", "remote", "add", "origin", REPO_URL], cwd=destination)
    run(["git", "fetch", "--depth", "1", "origin", COMMIT], cwd=destination)
    run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=destination)
    actual = run(
        ["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()
    if actual != COMMIT:
        raise RuntimeError(f"expected commit {COMMIT}, got {actual}")
    dirty = run(
        ["git", "status", "--porcelain"], cwd=destination).stdout.strip()
    if dirty:
        raise RuntimeError("external checkout is unexpectedly dirty")


def write_fixture(fixture: Path, checkout_dir: Path) -> None:
    fixture.mkdir(parents=True, exist_ok=True)
    policies = fixture / "policies"
    policies.mkdir()
    for name in ("aes.c", "aes.h", "unlicense.txt"):
        shutil.copy2(checkout_dir / name, fixture / name)
    (fixture / "algorithm_lib.cpp").write_text(
        ALGORITHM_LIB.lstrip(), encoding="utf-8", newline="\n")
    (fixture / "driver.cpp").write_text(
        DRIVER.lstrip(), encoding="utf-8", newline="\n")

    profiles = {
        "baseline": {
            "optflags": ["-O2"],
            "pipeline": "default<O2>",
            "strip": True,
        },
    }
    for index, (name, profile, level) in enumerate(
            (("aegis-standard", "release", 1),
             ("aegis-research", "research", 2),
             ("aegis-flattened", "research", 3)), start=1):
        policy_name = f"{name}.json"
        policy = {
            "schema_version": 1,
            "profile": profile,
            "seed": 20261115 + index,
            "functions": [{
                "name": "aegis_external_aes_block",
                "level": level,
                "reason": "pinned external tiny-AES workload",
            }],
            "limits": {
                "max_binary_growth_percent": 100,
                "max_p95_slowdown_percent": 100,
            },
        }
        (policies / policy_name).write_text(
            json.dumps(policy, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        profiles[name] = {
            "optflags": ["-O2"],
            "policy": f"policies/{policy_name}",
            "pipeline": (
                "aegis-policy<policy={policy}>,aegis-decoys,aegis-cff,"
                "default<O2>,aegis-verify"),
            "strip": True,
        }
    (fixture / "profiles.json").write_text(
        json.dumps({"profiles": profiles}, indent=2) + "\n",
        encoding="utf-8", newline="\n")


def write_markdown(report: dict, path: Path) -> None:
    rows = []
    baseline = report["profiles"]["baseline"]
    base_text = baseline.get("sections", {}).get("text", 0)
    for name, entry in report["profiles"].items():
        text = entry.get("sections", {}).get("text", 0)
        text_delta = ((text / base_text - 1.0) * 100.0
                      if base_text else 0.0)
        rows.append(
            f"| `{name}` | {text} | {text_delta:+.2f}% | "
            f"{entry.get('relative_p95_delta_pct', 0.0):+.2f}% | "
            f"{entry.get('build_median_ms', 0.0):.1f} | "
            f"{entry.get('mismatches', 0)} | "
            f"{entry.get('sanitizer_or_property_errors', 0)} |")
    lines = [
        "# External workload: tiny-AES-c",
        "",
        "Generated by `tests/external/run_tiny_aes.py`.",
        "",
        f"- source: `{REPO_URL}`",
        f"- commit: `{COMMIT}`",
        f"- license: `{LICENSE}`",
        f"- benchmark source commit: "
        f"`{report['benchmark_environment']['commit']}` "
        f"(dirty: {report['benchmark_environment']['commit_dirty']})",
        f"- source files: `aes.c`, `aes.h` copied into a temporary fixture",
        f"- corpus: {report['corpus_size']} deterministic cases",
        f"- build samples per profile: {report['build_samples_required']}",
        f"- mode: AES-128 ECB wrapper, baseline vs Aegis levels 1-3",
        "",
        "| Profile | `.text` | `.text` delta | paired p95 | "
        "build median ms | mismatches | sanitizer/property errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "## Scope",
        "",
        "This checks semantic preservation, code-size and runtime behaviour on",
        "one pinned public-domain C implementation. It is an external",
        "compatibility smoke, not a production benchmark and not evidence of",
        "attack resistance. The upstream project is not vendored into the",
        "repository; the script fetches the exact commit at run time.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--report", default=None)
    parser.add_argument("--markdown", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv[1:])

    plugin = Path(args.plugin).resolve()
    if not plugin.is_file():
        print(f"error: plugin not found: {plugin}", file=sys.stderr)
        return 2
    if shutil.which("git") is None:
        print("error: git is required for the external checkout",
              file=sys.stderr)
        return 2

    root = (Path(args.workdir).resolve() if args.workdir
            else Path(tempfile.mkdtemp(prefix="aegis-tiny-aes-")))
    root.mkdir(parents=True, exist_ok=True)
    external = root / "upstream"
    fixture = root / "fixture"
    raw_report = root / "raw-report.json"
    try:
        checkout(external)
        write_fixture(fixture, external)
        run([
            sys.executable,
            str(DIFFERENTIAL),
            "--plugin", str(plugin),
            "--fixture-dir", str(fixture),
            "--profiles", str(fixture / "profiles.json"),
            "--fuzz-cases", "40",
            "--build-samples", "3",
            "--report", str(raw_report),
        ], timeout=600)
        report = json.loads(raw_report.read_text(encoding="utf-8"))
        report["external_source"] = {
            "repository": REPO_URL,
            "commit": COMMIT,
            "license": LICENSE,
            "fetched_utc": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files": {
                "aes.c": sha256(fixture / "aes.c"),
                "aes.h": sha256(fixture / "aes.h"),
            },
        }
        report["benchmark_environment"] = benchmark_environment()
        report["fixture"] = "tiny-AES-c"
        report["fixture_dir"] = f"pinned:{REPO_URL}@{COMMIT}"
        report["profiles_source"] = (
            "generated:tests/external/run_tiny_aes.py")
        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2) + "\n",
                encoding="utf-8", newline="\n")
            print(f"report written to {report_path}")
        if args.markdown:
            markdown_path = Path(args.markdown)
            write_markdown(report, markdown_path)
            print(f"markdown written to {markdown_path}")
        for name, entry in report["profiles"].items():
            print(
                f"{name}: text={entry.get('sections', {}).get('text', 0)} "
                f"p95_delta={entry['relative_p95_delta_pct']:.2f}% "
                f"mismatches={entry['mismatches']}")
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"external smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep and args.workdir is None:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
