# Aegis-IR

**LLVM IR-level protection + a reproducible benchmark for the cost of AI-assisted reverse engineering.**

Aegis-IR is an open-source project with two deliverables:

- **Aegis-Bench** *(main product, in development)* — a reproducible benchmark that measures what an LLM-based reverse-engineering agent actually pays to recover a binary's semantics: tokens, wall-clock time, tool calls, and corrected task rate. Its unit of analysis is the *cost delta* produced by a protection transform, not "can an AI be defeated".
- **Aegis-IR pass plugin** *(companion)* — an LLVM New-PM plugin that applies policy-driven, semantics-preserving protection transforms at the IR level (first transform under development: decoy injection). It is the subject under test for the benchmark, not the project's headline.

## Status

`v0.1.0-alpha` development. The current tree contains only the read-only
`aegis-audit` pass, which exists to prove the plugin/CI pipeline. **No
protection transform is enabled yet.** Nothing here has been benchmarked.

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
opt-23 -load-pass-plugin=build/lib/AegisPass.so "aegis-audit" -disable-output build/demo.ll
# or: opt-23 -load-pass-plugin=build/lib/AegisPass.so -passes=aegis-audit -disable-output build/demo.ll
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