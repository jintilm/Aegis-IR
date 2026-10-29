# Aegis-IR

**LLVM IR-level protection + a reproducible benchmark for the cost of AI-assisted reverse engineering.**

Aegis-IR is an open-source project with two deliverables:

- **Aegis-Bench** *(main product)* — a reproducible benchmark that measures what an LLM-based reverse-engineering agent actually pays to recover a binary's semantics: tokens, wall-clock time, tool calls, and corrected task rate. Its unit of analysis is the *cost delta* produced by a protection transform, not "can an AI be defeated". The harness (task schema, independent grader, runner, report generator) exists and is tested; **no run against a real model has been published yet.**
- **Aegis-IR pass plugin** *(companion)* — an LLVM New-PM plugin that applies policy-driven, semantics-preserving protection transforms at the IR level (today: Tier-1 decoy injection). It is the subject under test for the benchmark, not the project's headline.

## The problem

Software shipped as binaries is increasingly fed to LLM-based reverse
engineering. Teams deciding whether to spend effort on software protection have
no honest, reproducible way to measure what that effort buys. Vendor claims are
unfalsifiable, and "our obfuscator defeats AI" is not a measurable statement.

This project takes the position that the only defensible claim is a **cost
delta at a fixed success criterion**, measured on self-authored tasks, with the
attacker's budget and tooling recorded — and it publishes the unfavorable
numbers too.

## Status

`v0.1.0-alpha` — research prototype, not a hardened protector.

Present in the tree: `aegis-audit` (read-only summary), `aegis-policy`
(JSON → IR attributes), `aegis-decoys` (first transform), `aegis-verify`
(post-optimization build gate that fails closed), the Aegis-Bench harness, and
one public benchmark task.

Tier-1 decoys are the only transform. They are deliberately weak: they slow
down naive triage and give the benchmark ground truth, but they are ineffective
against an analyst holding the source. **No protection effectiveness has been
measured, and none is claimed.**

## Honest expectations

Read [`docs/threat-model.md`](docs/threat-model.md) before using anything from
this repository. In one sentence: semantics-preserving protection raises the
*cost* of recovery; it cannot make semantics unrecoverable (obfuscation
impossibility, Barak et al. 2001), and static-only protection is expected to
degrade against attackers capable of dynamic tracing.

Non-goals, permanently:

- no sandbox detection that changes business results (no "fake logic" for
  suspect environments),
- no anti-debugging that causes failures,
- no malware evasion features. This is a software-asset-protection tool;
  do not use it to attack software you have no rights to.

## Supported environment

Linux x86-64, LLVM/Clang 23.x (pinned), CMake ≥ 3.20, Ninja, C++17. Python
3.10+ (stdlib only) for the benchmark harness. Everything else — other LLVM
majors, Windows/macOS plugin builds, LTO, policy levels above 1 — is rejected
with a clear error rather than half-supported. Full matrix and rationale:
[`docs/compatibility.md`](docs/compatibility.md).

## Build

With the pinned development container (recommended; the source of every
published number):

```bash
docker build -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev

# inside the container:
export LLVM_DIR=$(llvm-config-23 --cmakedir)
cmake -S . -B build -G Ninja -DLLVM_DIR=$LLVM_DIR -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

## Run

Audit a module (read-only):

```bash
clang++-23 -O0 -S -emit-llvm examples/demo.cpp -o build/demo.ll
opt-23 -load-pass-plugin=build/lib/AegisPass.so -passes=aegis-audit \
  -disable-output build/demo.ll
```

Apply a policy (see [`docs/policy.md`](docs/policy.md)):

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>' \
  -S build/demo.ll -o build/demo.policied.ll
```

Apply policy + decoys and gate the result (see
[`docs/decoys.md`](docs/decoys.md)):

```bash
# frontend IR: the transform must run before inlining
clang++-23 -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  examples/demo.cpp -o build/demo.ll
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,default<O2>,aegis-verify' \
  build/demo.ll -S -o build/demo.protected.ll
```

The pipeline order is not stylistic: running the passes after inlining guards
dead IR, and `aegis-verify` fails the build in that case.

## Test

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```

Four suites: `aegis-policy`, `aegis-decoys`, `differential` (seven build
profiles × 235 corpus cases), `aegis-bench` (offline harness tests — no model,
no network, no credentials).

## Benchmark

```bash
cd tools/aegis-bench
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter ground-truth --profile baseline --out /tmp/bench
```

Real runs pass an adapter from outside this repository, so no vendor SDK or API
key enters the tree or CI. Protocol:
[`docs/benchmark-protocol.md`](docs/benchmark-protocol.md); harness:
[`tools/aegis-bench/README.md`](tools/aegis-bench/README.md).

## Cost and known limits

The only measured cost so far is on a self-authored fixture (offline C++
algorithm library): Tier-1 decoys move `.text` from 5023 to 6132 bytes
(**+22.1%**) with byte-identical program output on all 235 differential cases
(claim C-001 in [`docs/claims-ledger.md`](docs/claims-ledger.md), artifact in
[`docs/reports/harness-validation/`](docs/reports/harness-validation/README.md)).
That is one small synthetic program; do not extrapolate it to large codebases.

Known limits, stated so they are not discovered as surprises:

- decoys are visible in the source corpus and ineffective against a white-box
  analyst; they are not control-flow obfuscation;
- the guard branch is never taken, so coverage-guided tracing prunes it;
- benchmark cost columns are adapter self-reports, unverifiable by the harness;
- `aegis-debug` (unprotected `-O0 -g`) is the supported way to debug a
  protected program — not the protected build itself.

## Layout

```text
aegis-ir/
├── include/aegis/        # public headers (version, policy)
├── lib/                  # LLVM pass plugin sources
├── tools/aegis-bench/    # benchmark harness (main product)
├── benchmarks/           # self-authored benchmark tasks
├── tests/                # policy / decoy / differential / bench suites
├── docs/                 # threat model, architecture, CI, reports, ledgers
├── examples/             # tiny programs used in docs and smoke tests
├── docker/               # pinned development container
└── .github/workflows/    # CI
```

## Naming

`IR` means **Intermediate Representation**. This project is unrelated to any
"AegisIR"-style incident-response tooling.

## License

Apache-2.0 WITH LLVM-exception. See [`LICENSE`](LICENSE).
