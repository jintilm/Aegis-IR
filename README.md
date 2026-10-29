# Aegis-IR

**LLVM IR-level protection + a reproducible benchmark for the cost of AI-assisted reverse engineering.**

Aegis-IR is an open-source project with two deliverables:

- **Aegis-Bench** *(main product, in development)* — a reproducible benchmark that measures what an LLM-based reverse-engineering agent actually pays to recover a binary's semantics: tokens, wall-clock time, tool calls, and corrected task rate. Its unit of analysis is the *cost delta* produced by a protection transform, not "can an AI be defeated". The harness (task schema, independent grader, runner, report generator) exists and is tested; no benchmark run has been published yet.
- **Aegis-IR pass plugin** *(companion)* — an LLVM New-PM plugin that applies policy-driven, semantics-preserving protection transforms at the IR level (first transform under development: decoy injection). It is the subject under test for the benchmark, not the project's headline.

## Status

`v0.1.0-alpha` development. The tree contains the read-only `aegis-audit`
pass, the policy pass (`aegis-policy`), the first protection transform
(`aegis-decoys`) with its post-optimization build gate (`aegis-verify`), and
the Aegis-Bench harness with one public task. Tier-1 decoys are the only
transform today, and they are deliberately weak: they slow down naive triage
and give the benchmark ground truth, but they are ineffective against an
analyst with the source. **No protection effectiveness has been benchmarked
yet.**

## Honest expectations

This project will never claim "defeats all AI reverse engineering". Read
[`docs/threat-model.md`](docs/threat-model.md) before using anything from this
repository. In one sentence: semantics-preserving protection raises the *cost*
of recovery; it cannot make semantics unrecoverable (obfuscation impossibility,
Barak et al. 2001), and static-only protection is expected to degrade against
attackers capable of dynamic tracing.

Non-goals, permanently:

- no sandbox detection that changes business results (no "fake logic" for
  suspect environments),
- no anti-debugging that causes failures,
- no malware evasion features. This is a software-asset-protection tool;
  do not use it to attack software you have no rights to.

## Build

Requirements: Linux x86-64, LLVM/Clang 23.x (pinned; see
`docs/dev-environment.md`), CMake >= 3.20, Ninja, a C++17-capable compiler.

With the pinned development container (recommended):

```bash
docker build -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev

# inside the container:
export LLVM_DIR=$(llvm-config-23 --cmakedir)
cmake -S . -B build -G Ninja -DLLVM_DIR=$LLVM_DIR -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

Verify the plugin end to end:

```bash
clang++-23 -O0 -S -emit-llvm examples/demo.cpp -o build/demo.ll
opt-23 -load-pass-plugin=build/lib/AegisPass.so -passes=aegis-audit -disable-output build/demo.ll
```

Apply a policy (lowered to `aegis.level` attributes; see
[`docs/policy.md`](docs/policy.md)):

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>' \
  -S build/demo.ll -o build/demo.policied.ll
```

Apply policy + decoys and gate the result (see
[`docs/decoys.md`](docs/decoys.md)):

```bash
# compile to frontend IR: the transform must run before inlining
clang++-23 -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  examples/demo.cpp -o build/demo.ll
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,default<O2>,aegis-verify' \
  build/demo.ll -S -o build/demo.protected.ll
```

Run the test suite (inside the container):

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```

On non-Linux platforms the plugin artifact has a different extension
(`.dll` / `.dylib`); locate it with `find build -name '*AegisPass*'`.

## Layout

```text
aegis-ir/
├── include/aegis/        # public headers (version, policy, report)
├── lib/                  # LLVM pass plugin sources
├── tools/aegis-bench/    # benchmark harness (main product; in development)
├── examples/             # tiny programs used in docs and smoke tests
├── tests/                # unit / integration / differential tests
├── benchmarks/           # self-authored benchmark fixtures & task sets
├── docs/                 # threat model, architecture, protocol, checklists
├── docker/               # pinned development container
└── .github/workflows/    # CI
```

## Naming

`IR` means **Intermediate Representation**. This project is unrelated to any
"AegisIR"-style incident-response tooling.

## License

Apache-2.0 WITH LLVM-exception. See [`LICENSE`](LICENSE).