# Aegis-IR

[中文](README.md) | [English](README.en.md)

**Deterministic protection engineering and benchmarking for LLVM IR.**

Measure correctness, code size, runtime overhead, and build cost before enabling
code protection, so each profile has reproducible engineering evidence behind it.

[Quick start](#quick-start) · [Protect a module](#protect-a-module) · [Release gate](#release-gate) · [Aegis-Bench](#aegis-bench) · [Isolation](#isolation) · [Evidence](#evidence) · [Documentation](#documentation)

![version](https://img.shields.io/badge/version-0.4.1--alpha-blue)
![LLVM](https://img.shields.io/badge/LLVM-23.x-6f42c1)
![platform](https://img.shields.io/badge/platform-Linux%20x86--64-lightgrey)
![task schema](https://img.shields.io/badge/task%20schema-v4-green)
![license](https://img.shields.io/badge/license-Apache--2.0%20WITH%20LLVM--exception-blue)

> [!IMPORTANT]
> This project is in alpha and studies code protection and its engineering
> costs. Tests and scorecards check semantic preservation and overhead; they do
> not establish resistance to reverse engineering, production-average
> performance, or protection against a professional analyst.

<a id="what-this-is"></a>

## Project components

| Component | Role |
|---|---|
| **Aegis-Bench** | Main evaluation framework: correctness, `.text` size, paired p95, and build-time scorecards, plus campaign orchestration, resume, audit, and isolation |
| **Aegis-IR plugin** | Companion LLVM New Pass Manager plugin: policy-driven decoys, bogus flow, and control-flow transforms |
| **[Aegis-adapters](https://github.com/jintilm/Aegis-adapters)** | Model adapters in a separate repository: OpenAI-compatible endpoints for optional model experiments |

The project measures first, then selects a profile:

- Normal builds, tests, and releases do not call an LLM or require API keys.
- Unsupported protection requests fail explicitly, so a policy cannot silently
  claim protection that was skipped.
- Post-optimization verification checks that required protection structures
  survive, while differential execution checks program results.
- Public performance and effectiveness statements must cite reports and state
  their tasks, versions, and scope.

## At a glance

| Item | Current state |
|---|---|
| Public tasks | 12: six `core` and six `exploratory` |
| Protection levels | Level 0–3 |
| Differential workloads | A small regression fixture and a representative algorithm fixture with at least 1 MiB of work per invocation |
| Release checks | Eight CTest targets, including two model-free engineering scorecards |
| Build sampling | Median of three independent builds, interleaved by profile |
| Isolation | Separate processes, Landlock, seccomp, private network namespaces, and optional containers per cell |
| Hardening checks | ASan/UBSan, policy-parser libFuzzer, and Clang Static Analyzer |
| Release artifacts | Reproducible archive, SHA-256, CycloneDX SBOM, and cosign keyless signatures |
| Published release | [`v0.4.1-alpha`](https://github.com/jintilm/Aegis-IR/releases/tag/v0.4.1-alpha) |

The `main` branch may contain unreleased changes. Historical reports describe
their recorded commits and do not automatically represent the current worktree.

## Quick start

Use the Linux development image provided by this repository. The host needs Git
and Docker; the host commands below use Bash syntax.

```bash
git clone https://github.com/jintilm/Aegis-IR.git aegis-ir
cd aegis-ir

docker build -f docker/dev.Dockerfile -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev
```

Inside the container, configure, build, and run the tests:

```bash
export LLVM_DIR="$(llvm-config-23 --cmakedir)"
cmake -S . -B build -G Ninja -DLLVM_DIR="$LLVM_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
```

A release requires all eight CTest targets to pass. Performance checks depend
on host load; retain the original report after a failure and inspect the
environment and measurement conditions. Network-namespace tests also require
host permissions and skip the relevant checks when capabilities are missing;
see the [isolation documentation](docs/isolation.md).

The image pins Ubuntu 24.04 by digest and verifies the `llvm.sh` installer by
SHA-256. LLVM versions and native installation are covered in the
[development environment](docs/dev-environment.md). Windows users can run Linux
containers through Docker Desktop. With Git Bash, prefix the `docker run`
command above with `MSYS_NO_PATHCONV=1` to prevent path conversion.

Unless a step explicitly says to run on the host, commands involving compilers,
`opt`, or Bash scripts below run in this Linux environment. Each section starts
at the repository root unless its code block explicitly changes directory.

## Protect a module

### 1. Emit frontend IR

Protection transforms must run before inlining and other optimizations:

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

`aegis-lint` lists selected functions, eligibility, unsupported constructs, and
repair advice. For eligible Level 3 functions, it also reports loop count,
maximum loop depth, PHI nodes, and cross-block values to help plan cost
measurements. These are static structural hints, not measured hotspots, and
they do not automatically change policy levels.

### 3. Apply and verify protection

Level 1 pipeline:

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,default<O2>,aegis-verify' \
  -S build/demo.ll -o build/demo.protected.ll
```

When the policy selects Level 2 or Level 3, include the `aegis-cff` control-flow
pass:

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,aegis-cff,default<O2>,aegis-verify' \
  -S build/demo.ll -o build/demo.protected.ll
```

Compile the protected IR with the same target and ABI. Pipeline order is
required: skipping protection or losing required structures to optimization
fails verification. An explicitly empty policy or an all-Level-0 policy can
run as an unprotected pipeline.

See the [policy reference](docs/policy.md), [decoy transforms](docs/decoys.md),
and [control-flow transforms](docs/controlflow.md) for fields and restrictions.
For example, Level 3 currently rejects unsupported dynamic or non-entry
`alloca` instructions and C variable-length arrays before rewriting.

## Protection profiles

| Profile | Purpose | Release role |
|---|---|---|
| `baseline` | Original behavior | Control |
| `release` | Unprotected, stripped build | Control |
| `release-opt` | Same `opt` round trip without Aegis transforms | Small-fixture scorecard baseline |
| `aegis-standard` | Level 1 decoys | Default release profile |
| `aegis-research` | Level 2 input-dependent branching and bogus edges | Research observation; non-gating |
| `aegis-flattened` | Level 3 control-flow flattening with volatile state | Research observation; non-gating |
| `aegis-debug` | Unprotected `-O0 -g` build | Debugging |
| `baseline-asan` | ASan/UBSan checks | Correctness checks |

The default profile prioritizes engineering cost. Avoid applying Level 3
directly to hot paths; measure the target functions first. Policy `level`
numbers identify this plugin's transforms and are not the capability tiers in
the [threat model](docs/threat-model.md).

The table lists differential-evaluation profiles. Public binary-recovery tasks
typically name their artifact profiles `baseline`, `aegis-level1`,
`aegis-level2`, and `aegis-level3`; each task's `task.json` is authoritative.

## Release gate

The scorecards enforce these budgets for the default `aegis-standard` profile:

| Metric | Small fixture | Representative fixture |
|---|---:|---:|
| Output mismatches | 0 | 0 |
| Sanitizer / property errors | 0 | 0 |
| `.text` growth | ≤ 25% | ≤ 30% |
| Paired relative p95 growth | ≤ 25% | ≤ 25% |
| Build-time median growth | ≤ 25% | ≤ 30% |
| Independent builds per arm | 3 | 3 |

The small fixture uses `release-opt` as its performance baseline. The
representative fixture uses its own `baseline`, which already includes the
same `opt` round trip. Profiles are interleaved during sampling to reduce
warm-up and host-load drift affecting one arm disproportionately.

Paired p95 compares the mean protected and baseline latency for each case,
then takes the 95th percentile of those ratios. A ratio of two independently
collected p95 values is not a substitute. Reports record
`runtime_baseline_profile` and per-case samples; a mismatched baseline or
incomplete paired measurement fails the scorecard.

Generate and score both reports:

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

Outputs include `scorecard.json` and `scorecard.md`. Older reports without the
baseline stamp need new measurements before they can be used with the current
gate; published historical reports remain unchanged. See the
[engineering scorecard documentation](docs/protection-scorecard.md) for
budgets and measurement limits.

<a id="aegis-bench"></a>

## Aegis-Bench evaluation framework

Run model-free experiments to check task content, resume behavior, and audit
results:

```bash
cd tools/aegis-bench
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
  --experiment ../../experiments/offline-smoke.json
```

Capabilities include:

- Task schema v4 with explicit `core` and `exploratory` tiers.
- Content hashes, hidden cases, property tests, and differential grading.
- Campaign orchestration across configurations, interleaved ordering, atomic
  checkpoints, resume, and independent audit.
- Harness-owned tool broker, oracle query accounting, and optional model token
  metering.
- Verified private artifact snapshots, output limits during reads, cancellation,
  and resource cleanup.
- Process and container workers, plus Wilson intervals and provenance in reports.

Single-run screening and repeated comparisons provide different evidence.
Only `packed-record-v1` currently has N=5 calibration records for both pilot
models; N=1 results must not be presented as N=5 evidence.

Read the [harness guide](tools/aegis-bench/README.md),
[benchmark protocol](docs/benchmark-protocol.md), and
[campaign and audit contract](docs/campaigns.md).

## Isolation

| Mode | Intended use and boundary |
|---|---|
| `in-process` | Runs in the harness process; debugging and trusted offline adapters only |
| `process` | Fresh worker per cell, workspace-only view, optional Landlock, seccomp, and private network namespace |
| `container` | Non-root container per cell, read-only root, no network, dropped capabilities, resource limits, and explicit mounts |

Broker execution and disassembly use a private artifact snapshot verified by
SHA-256. The worker's workspace copy is available for observation but is not
the trusted broker's execution target. Oracle mode calls the service that
counts queries and enforces budgets directly. Shutdown cancels active work
before collecting final counters and removing snapshots.

Container mode mounts only the workspace, per-run transport directory,
read-only harness and adapter directories, and broker/meter Unix sockets.
The real container smoke needs a running Docker daemon. Run it on a host that
can access that daemon and the source directory:

```bash
python3 tests/container/run_smoke.py \
  --runtime docker --image aegis-ir-dev --user 65534:65534
```

Process timeouts and output caps do not replace a sandbox. Isolating the
adapter worker also does not mean the grader runs in a separate container.
See the [isolation documentation](docs/isolation.md) and
[adapter contract](docs/reference-adapter.md) for the actual trust boundaries.

<a id="evidence"></a>

## Evidence and releases

| Evidence | Location |
|---|---|
| Published release | [`v0.4.1-alpha`](https://github.com/jintilm/Aegis-IR/releases/tag/v0.4.1-alpha) |
| Release workflow | [Workflow source](.github/workflows/release.yml) · [Historical release run](https://github.com/jintilm/Aegis-IR/actions/runs/43695572417) |
| Checked-in versioned full validation report | [`harness-validation-v0.4.0-alpha`](docs/reports/harness-validation-v0.4.0-alpha/README.md) |
| External C workload including LTO | [`external-tiny-aes-c-2385675`](docs/reports/external-tiny-aes-c-2385675/README.md) |
| All reports and their scope | [Report index](docs/reports/README.md) |
| Public claims and supporting evidence | [Claims ledger](docs/claims-ledger.md) |

The release workflow is configured to build and test, generate an SBOM, sign
the archive and `SHA256SUMS`, verify signatures, and publish a GitHub Release.
Packaging stops if it cannot create the test log or CTest reports a failure.

To generate a new local validation report, run the following from a clean
repository root in Bash on a host with Docker access. The script starts the
development container with the required capabilities:

```bash
bash scripts/release-report.sh harness-validation-local
```

Each report records the source commit and worktree state. Historical reports
do not cover new commits or replace validation of current code.

## Compatibility

Supported environment:

- Linux x86-64.
- LLVM/Clang 23.x; use the provided development image where possible.
- CMake ≥ 3.20, Ninja, and C++17.
- Python 3.10+; the benchmark harness uses only the standard library.

Native Windows/macOS plugin builds are unsupported, and other LLVM majors
are not guaranteed to work. Multi-module regressions cover ordinary and LTO
links, and the external compatibility fixture includes a `-flto` profile.
This coverage does not establish support for every LTO combination in arbitrary
projects. See the [compatibility documentation](docs/compatibility.md) for more
platform details.

## Development checks

Normal tests:

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure
```

The eight CTest targets are `aegis-policy`, `aegis-decoys`,
`aegis-controlflow`, `differential`, `differential-representative`,
`protection-scorecard`, `protection-scorecard-representative`, and `aegis-bench`.

Additional hardening checks and packaging regressions:

```bash
bash scripts/sanitizer-check.sh
bash scripts/fuzz-policy.sh
bash scripts/static-analysis.sh
python3 -m unittest discover -s tests/package -v
```

The pinned external workload fetches third-party source, so it runs separately
from CTest:

```bash
python3 tests/external/run_tiny_aes.py \
  --plugin build/lib/AegisPass.so \
  --report build/tiny-aes-external-report.json \
  --markdown build/tiny-aes-external-report.md
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributions and
[SECURITY.md](SECURITY.md) for reporting security issues.

<a id="optional-model-research"></a>

## Optional model experiments

Real-model campaigns study recovery cost under specific conditions and are not
required for normal releases. The separate
[Aegis-adapters](https://github.com/jintilm/Aegis-adapters) repository provides
OpenAI-compatible API access, complete effective configurations, and
configuration fingerprints, integrating with this harness's tools, metering,
and resume mechanisms.

Use `binary` access to compare protection levels. `oracle` access provides
identical black-box behavior across profiles and cannot measure the effect of
static protection transforms. Old model-only reference-adapter configurations
must migrate to complete `effective_options()`; placeholder values in the
example manifest cannot start a valid experiment. See the
[adapter contract](docs/reference-adapter.md) for configuration generation.

Existing pilots are kept in the [report directory](docs/reports/README.md).
Incomplete token metering, small samples, or comparisons without fixed success
criteria limit how results can be interpreted. They cannot establish a reduced
recovery success rate or general resistance to reverse engineering.

<a id="security-posture-and-non-goals"></a>

## Protection limits and non-goals

Semantics-preserving transforms can only attempt to raise recovery cost; they
cannot make semantics permanently unrecoverable. Dynamic tracing, white-box
analysis, and analysts with the source code are explicit limits of this project.

The project does not provide:

- Environment detection that changes business results.
- Anti-debugging that causes incorrect behavior or crashes.
- Features intended to evade malware analysis.
- Protection of software you do not have rights to protect.

Read the [threat model](docs/threat-model.md) before deployment. Client-side
obfuscation does not replace server-side authentication, authorization, or
secure key management.

## Repository layout

```text
include/aegis/        Public headers
lib/                 LLVM Pass plugin
tools/aegis-bench/    Benchmark harness and engineering scorecards
benchmarks/          Public task definitions
experiments/         Campaign and budget configurations
tests/               Policy, transform, differential, packaging, and isolation tests
docs/                Protocols, threat model, reports, and claims ledger
docker/              Pinned development environment
.github/workflows/    CI and signed release workflows
```

## Documentation

Detailed technical documents are currently mostly in English.

- [Architecture](docs/architecture.md)
- [Policy reference](docs/policy.md)
- [Decoy transforms](docs/decoys.md)
- [Control-flow transforms](docs/controlflow.md)
- [Engineering scorecard](docs/protection-scorecard.md)
- [Benchmark protocol](docs/benchmark-protocol.md)
- [Campaigns and audit](docs/campaigns.md)
- [Isolation](docs/isolation.md)
- [Model adapter contract](docs/reference-adapter.md)
- [Release checklist](docs/release-checklist.md)
- [Release signing](docs/release-signing.md)
- [Claims and evidence](docs/claims-ledger.md)

## Naming

`IR` means **Intermediate Representation**. This project is unrelated to
AegisIR-style incident-response tooling.

## License

Apache-2.0 WITH LLVM-exception. See [LICENSE](LICENSE).
