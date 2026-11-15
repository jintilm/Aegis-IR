# Aegis-IR

**Deterministic protection engineering for LLVM IR.**

Measure correctness, code size, runtime and build cost before shipping an
obfuscation profile.

[Quick start](#quick-start) · [Protect a module](#protect-a-module) ·
[Release gate](#release-gate) · [Aegis-Bench](#aegis-bench) ·
[Isolation](#isolation) · [Evidence](#evidence) · [Documentation](#documentation)

![version](https://img.shields.io/badge/version-0.4.1--alpha-blue)
![LLVM](https://img.shields.io/badge/LLVM-23.x-6f42c1)
![platform](https://img.shields.io/badge/platform-Linux%20x86--64-lightgrey)
![task schema](https://img.shields.io/badge/task%20schema-v4-green)
![license](https://img.shields.io/badge/license-Apache--2.0%20WITH%20LLVM--exception-blue)

> [!IMPORTANT]
> Aegis-IR is an alpha-stage protection engineering project, not a hardened
> protector. It measures cost and semantic preservation; it does **not** claim
> attack effectiveness, production-average overhead or resistance to a
> determined human analyst.

## What this is

Aegis-IR has two parts:

| Component | Role |
|---|---|
| **Aegis-Bench** | Main product: a model-free scorecard and benchmark harness for correctness, `.text`, paired p95, build time, campaigns, resume, audit and isolation |
| **Aegis-IR plugin** | Companion LLVM New-PM plugin that applies policy-driven decoys, bogus flow and control-flow transforms |

The design is measurement-first:

- normal builds and releases do not call an LLM;
- unsupported transforms fail closed instead of silently skipping;
- every public claim points to a checked-in artifact;
- performance and effectiveness claims are limited to what the evidence
  actually supports.

## At a glance

| Item | Current state |
|---|---|
| Public tasks | 12, split six `core` and six `exploratory` |
| Protection levels | 0–3 |
| Differential workloads | Small fixture plus a representative 1 MiB minimum-work suite |
| Release gates | 8 CTest targets and two deterministic scorecards |
| Build sampling | Median of three independent, profile-interleaved clean builds |
| Isolation | Process, Landlock, seccomp, private network namespace and optional container-per-cell |
| Security gates | ASan+UBSan, policy-parser libFuzzer and Clang Static Analyzer |
| Release artifacts | Reproducible tarball, SHA-256, CycloneDX SBOM and cosign keyless signatures |
| Current release | [`v0.4.1-alpha`](https://github.com/jintilm/Aegis-IR/releases/tag/v0.4.1-alpha) |

## Quick start

Build and enter the pinned environment:

```bash
docker build -f docker/dev.Dockerfile -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev
```

Inside the container:

```bash
export LLVM_DIR="$(llvm-config-23 --cmakedir)"
cmake -S . -B build -G Ninja -DLLVM_DIR="$LLVM_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Expected result: all eight CTest targets pass. The container pins Ubuntu 24.04
by digest and verifies the `llvm.sh` installer by SHA-256.

## Protect a module

### 1. Emit frontend IR

Protection must run before inlining:

```bash
clang++-23 -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  examples/demo.cpp -o build/demo.ll
```

### 2. Check policy eligibility

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-lint' \
  -disable-output build/demo.ll
```

`aegis-lint` reports selected, eligible, ineligible and unsupported functions,
plus `protect-and-measure`, `move-to-server` or a reason-specific repair
advisory.

### 3. Apply and verify protection

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,default<O2>,aegis-verify' \
  -S build/demo.ll -o build/demo.protected.ll
```

For levels 2/3, add the control-flow pass:

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,aegis-cff,default<O2>,aegis-verify' \
  -S build/demo.ll -o build/demo.protected.ll
```

Then compile the protected IR with the same target and ABI. See
[`docs/policy.md`](docs/policy.md), [`docs/decoys.md`](docs/decoys.md) and
[`docs/controlflow.md`](docs/controlflow.md).

## Protection profiles

| Profile | Purpose | Release role |
|---|---|---|
| `baseline` | Reference behavior | Observation |
| `release-opt` | Same `opt` round trip without Aegis transforms | Scorecard baseline |
| `aegis-standard` | Level-1 decoys | Default release gate |
| `aegis-research` | Level 2: live split and bogus edges | Non-gating research |
| `aegis-flattened` | Level 3: volatile-state flattening | Non-gating research |
| `aegis-debug` | Unprotected `-O0 -g` debugging artifact | Debugging |
| `baseline-asan` | ASan+UBSan safety net | Observation |

The default is deliberately the cheapest profile. Flattening is not
recommended for hot paths.

## Release gate

The deterministic scorecard gates the default profile against the shared
`release-opt` baseline:

| Budget | Small fixture | Representative |
|---|---:|---:|
| Output mismatches | 0 | 0 |
| Sanitizer/property errors | 0 | 0 |
| `.text` growth | ≤ 25% | ≤ 30% |
| Paired relative p95 | ≤ 25% | ≤ 25% |
| Build median growth | ≤ 25% | ≤ 30% |
| Build samples | 3 | 3 |

Build samples are interleaved by profile so one arm cannot absorb all compiler
warm-up or host-load drift.

Run the scorecards:

```bash
python3 tests/differential/run.py \
  --plugin build/lib/AegisPass.so \
  --report build/differential-report.json

cd tools/aegis-bench
python3 -m aegis_bench scorecard \
  --differential ../../build/differential-report.json \
  --budgets ../../experiments/protection-budgets.json \
  --out ../../build/scorecard

python3 ../../tests/differential/run.py \
  --plugin ../../build/lib/AegisPass.so \
  --fixture-dir ../../tests/differential/suites/representative \
  --profiles ../../tests/differential/suites/representative/profiles.json \
  --fuzz-cases 40 \
  --report ../../build/representative-differential-report.json

python3 -m aegis_bench scorecard \
  --differential ../../build/representative-differential-report.json \
  --budgets ../../experiments/protection-budgets-representative.json \
  --out ../../build/scorecard-representative
```

Details and limitations:
[`docs/protection-scorecard.md`](docs/protection-scorecard.md).

## Aegis-Bench

Use the harness when you need reproducible task results, not just a pass/fail
build gate:

```bash
cd tools/aegis-bench
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
  --experiment ../../experiments/offline-smoke.json
```

Implemented capabilities:

- task schema v4 with `core` and `exploratory` tiers;
- content hashes, hidden cases, property tests and differential grading;
- campaign interleaving, atomic checkpoints, resume and independent audit;
- harness-owned tool broker, oracle accounting and optional provider meter;
- process and container worker boundaries;
- Wilson intervals and provenance in generated reports.

Calibration evidence distinguishes N=1 screening from N=5 comparison data.
Only `packed-record-v1` currently has N=5 records for both pilot models; an N=1
result is never presented as N=5 evidence.

Harness guide:
[`tools/aegis-bench/README.md`](tools/aegis-bench/README.md). Protocol:
[`docs/benchmark-protocol.md`](docs/benchmark-protocol.md). Campaign contract:
[`docs/campaigns.md`](docs/campaigns.md).

## Isolation

| Mode | Boundary |
|---|---|
| `in-process` | Debugging and trusted offline adapters only |
| `process` | Fresh worker, workspace-only `TaskView`, optional Landlock/seccomp/netns |
| `container` | Non-root container, read-only root, network none, capabilities dropped, no-new-privileges, resource limits and explicit mounts |

Container mode mounts only the workspace, per-run transport, read-only
Aegis/adapter paths and broker/meter Unix sockets. The real-runtime smoke is:

```bash
python3 tests/container/run_smoke.py \
  --runtime docker --image aegis-ir-dev --user 65534:65534
```

See [`docs/isolation.md`](docs/isolation.md) and
[`docs/reference-adapter.md`](docs/reference-adapter.md).

## Evidence

| Evidence | Artifact |
|---|---|
| Current signed release | [`v0.4.1-alpha`](https://github.com/jintilm/Aegis-IR/releases/tag/v0.4.1-alpha) |
| Release workflow | [GitHub Actions release run](https://github.com/jintilm/Aegis-IR/actions/runs/43695572417) |
| Latest checked-in full validation report | [`harness-validation-v0.4.0-alpha`](docs/reports/harness-validation-v0.4.0-alpha/README.md) |
| External C workload with LTO | [`external-tiny-aes-c-2385675`](docs/reports/external-tiny-aes-c-2385675/README.md) |
| Claim wording and evidence scope | [`docs/claims-ledger.md`](docs/claims-ledger.md) |

The `v0.4.1-alpha` release workflow rebuilt the archive, ran the complete test
suite, generated the SBOM, signed the tarball and `SHA256SUMS` with Sigstore,
verified both signatures and published the GitHub Release.

Reproduce a clean-tree report:

```bash
bash scripts/release-report.sh harness-validation-local
```

## Compatibility

Supported today:

- Linux x86-64
- LLVM/Clang 23.x, pinned by the development container
- CMake ≥ 3.20 and Ninja
- C++17
- Python 3.10+ with standard library only for the benchmark harness

The external compatibility workload also exercises a `-flto` profile. Full LTO
support for arbitrary project builds is not claimed. Windows/macOS plugin
builds, other LLVM majors and unsupported IR constructs fail rather than
degrading silently. Full matrix:
[`docs/compatibility.md`](docs/compatibility.md).

## Development checks

Normal test suite:

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure
```

The eight CTest targets are:

`aegis-policy`, `aegis-decoys`, `aegis-controlflow`, `differential`,
`differential-representative`, `protection-scorecard`,
`protection-scorecard-representative` and `aegis-bench`.

Additional hardening gates:

```bash
bash scripts/sanitizer-check.sh
bash scripts/fuzz-policy.sh
bash scripts/static-analysis.sh
```

The external pinned workload is intentionally outside CTest because it fetches
third-party source:

```bash
python3 tests/external/run_tiny_aes.py \
  --plugin build/lib/AegisPass.so \
  --report build/tiny-aes-external-report.json \
  --markdown build/tiny-aes-external-report.md
```

## Security posture and non-goals

Semantics-preserving protection can raise recovery cost; it cannot make
semantics unrecoverable. Static-only transforms are expected to degrade
against dynamic tracing and a white-box analyst with this source tree.

Permanent non-goals:

- no environment detection that changes business results;
- no anti-debugging that causes failures;
- no malware evasion;
- no use against software you do not have rights to protect.

Read [`docs/threat-model.md`](docs/threat-model.md) before deployment.

## Optional model research

Model campaigns are selective research, not a release requirement. The adapter
lives outside this repository, and no vendor SDK or API key is needed to build,
test or release Aegis-IR.

The latest dual-model N=5 pilot measured descriptive metered-token floors of
2.15× and 3.03× on one task. Success was not held fixed and 125 abandoned calls
carried no usage, so the result is not an effectiveness claim. Published pilots
remain under [`docs/reports/`](docs/reports/README.md).

## Repository layout

```text
include/aegis/        public headers
lib/                  LLVM pass plugin
tools/aegis-bench/    deterministic harness and scorecard
benchmarks/           public task definitions
experiments/          campaign and budget manifests
tests/                policy, transform, differential and isolation tests
docs/                 protocol, threat model, reports and ledgers
docker/               pinned development image
.github/workflows/    CI and signed release workflows
```

## Documentation

- [Architecture](docs/architecture.md)
- [Policy reference](docs/policy.md)
- [Decoys](docs/decoys.md)
- [Control-flow transforms](docs/controlflow.md)
- [Protection scorecard](docs/protection-scorecard.md)
- [Benchmark protocol](docs/benchmark-protocol.md)
- [Campaigns and audit](docs/campaigns.md)
- [Isolation](docs/isolation.md)
- [Release checklist](docs/release-checklist.md)
- [Release signing](docs/release-signing.md)
- [Claims ledger](docs/claims-ledger.md)

## Naming

`IR` means **Intermediate Representation**. This project is unrelated to
AegisIR-style incident-response tooling.

## License

Apache-2.0 WITH LLVM-exception. See [`LICENSE`](LICENSE).
