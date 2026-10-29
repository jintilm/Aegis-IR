# Aegis-IR

**LLVM IR-level protection + a reproducible benchmark for the cost of AI-assisted reverse engineering.**

Aegis-IR is an open-source project with two deliverables:

- **Aegis-Bench** *(main product)* — a reproducible benchmark that measures what an LLM-based reverse-engineering agent actually pays to recover a binary's semantics: tokens, wall-clock time, tool calls, and corrected task rate. Its unit of analysis is the *cost delta* produced by a protection transform, not "can an AI be defeated". The harness (task schema, independent grader, runner, report generator) exists and is tested; **no run against a real model has been published yet.**
- **Aegis-IR pass plugin** *(companion)* — an LLVM New-PM plugin that applies policy-driven, semantics-preserving protection transforms at the IR level (decoys, bogus flow, control-flow flattening). It is the subject under test for the benchmark, not the project's headline.

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
(JSON → IR attributes), `aegis-decoys` (level-1 transform), `aegis-cff`
(level 2/3 control-flow transforms), `aegis-verify` (post-optimization build
gate that fails closed), the Aegis-Bench harness, and one public benchmark
task.

Level 1 decoys are the default and remain deliberately weak: they slow down
naive triage and give the benchmark ground truth, but they are ineffective
against an analyst holding the source. Levels 2/3 (input-driven live split,
bogus edges, volatile-state flattening) raise *static* reconstruction cost and
are off by default; they are not the threat model's Tier 2/3. **No protection
effectiveness has been measured, and none is claimed.**

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
majors, Windows/macOS plugin builds, LTO, policy levels outside `0..3`, and
level-3 flattening of `indirectbr`/`callbr`/coroutine/EH constructs — is
rejected with a clear error rather than half-supported. Full matrix and
rationale: [`docs/compatibility.md`](docs/compatibility.md).

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

For policy levels 2/3 (bogus flow, live split, flattening), add `aegis-cff`
after the decoys:

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,aegis-cff,default<O2>,aegis-verify' \
  build/demo.ll -S -o build/demo.protected.ll
```

See [`docs/controlflow.md`](docs/controlflow.md) for the invariants, the
fail-loud eligibility list and what the transforms do **not** do.

## Test

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```

Five suites: `aegis-policy`, `aegis-decoys`, `aegis-controlflow`,
`differential` (eight build profiles × 235 corpus cases), `aegis-bench`
(offline harness tests — no model, no network, no credentials).

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

The only measured costs so far are on a self-authored fixture (offline C++
algorithm library), all with byte-identical program output on the 235
differential cases:

| Profile | `.text` | Delta | Claim |
|---|---|---|---|
| baseline | 5023 B | — | — |
| level 1 decoys | 6132 B | +22.1% | C-001 |
| level 2 (live split + bogus edges) | 5672 B | +12.9% | C-003 |
| level 3 (+ flattening) | 6642 B | +32.2% | C-004 |

The research profiles use different seeds, so they are each comparable to the
shared baseline, not to each other as a ladder. That is one small synthetic
program; do not extrapolate it to large codebases. Details and scope:
[`docs/claims-ledger.md`](docs/claims-ledger.md), artifact in
[`docs/reports/harness-validation/`](docs/reports/harness-validation/README.md).

Known limits, stated so they are not discovered as surprises:

- decoys are visible in the source corpus and ineffective against a white-box
  analyst;
- the level-1 guard branch is never taken, so coverage-guided tracing prunes
  it; level 2's live split makes the executed path input-dependent, but the
  flattening dispatcher is visible to a dynamic trace;
- level 3 is local static-cost obfuscation, not the threat model's Tier 3
  (semantics removal); the state encoding key derives from the shipped seed;
- flattening costs a volatile load and store per basic block; it is not
  recommended for hot paths;
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
