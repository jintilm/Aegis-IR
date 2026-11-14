# Aegis-IR

**LLVM IR-level protection with deterministic engineering scores and optional AI-cost studies.**

Aegis-IR is an open-source project with two deliverables:

- **Aegis-Bench** *(main product)* — a deterministic protection engineering scorecard plus an optional model-cost harness. The default release path runs no LLM and gates correctness, `.text`, paired p95 and build-time budgets through [`docs/protection-scorecard.md`](docs/protection-scorecard.md). Model campaigns remain available for targeted research questions, but they are not routine release evidence. A historical dual-model N=5 pilot measured metered token floors of 2.15× and 3.03× on one task; its arms did not hold success fixed, so that result is descriptive only. **No effectiveness claim is drawn from any report.**
- **Aegis-IR pass plugin** *(companion)* — an LLVM New-PM plugin that applies policy-driven, semantics-preserving protection transforms at the IR level (decoys, bogus flow, control-flow flattening). It is the subject under test for the benchmark, not the project's headline.

## The problem

Software protection is usually sold with unfalsifiable claims. Engineering
teams need to know whether a transform preserves behaviour, how much code and
runtime it costs, and whether it stays inside a release budget. Separately,
LLM-based reverse engineering can be studied as an optional research question,
but an AI-versus-AI loop is a poor substitute for deterministic engineering
evidence.

This project therefore treats the deterministic scorecard as the normal gate
and model campaigns as selective, explicitly scoped experiments.

## Status

`v0.3.0-alpha` — protection engineering prototype, not a hardened protector.
The deterministic scorecard is the default release path. Campaign/resume/audit
and harness-owned token/tool brokers remain available for optional model
research. The harness also includes an optional adapter subprocess boundary.
The current unreleased tree adds task schema v4 (`core`/`exploratory` tiers),
twelve validated public tasks, three-build median reporting, a larger
representative differential workload, and eight release-gating CTest targets.
It has not yet been cut as a new version.
Linux `require_sandbox` workers use Landlock for workspace/runtime file access
and broker/meter TCP-port restriction; seccomp denies non-stream IP sockets. The
opt-in `require_network_namespace` path gives the worker a private loopback
namespace and bridges broker/meter over per-run Unix sockets, removing direct
host-network reachability.

Present in the tree: `aegis-audit` (read-only summary), `aegis-lint`
(read-only protectability preflight), `aegis-policy`
(JSON → IR attributes), `aegis-decoys` (level-1 transform), `aegis-cff`
(level 2/3 control-flow transforms), `aegis-verify` (post-optimization build
gate that fails closed), the Aegis-Bench harness with binary-recovery tasks,
and twelve public benchmark tasks (`rolling-token-v1`, `rolling-token-v2`,
`packed-record-v1`, `lane-shift-v1`, `window-parser-v1`, `state-fold-v1`,
`ring-drain-v1`, `grid-route-v1`, `delta-ledger-v1`, `sbox-cascade-v1`,
`bit-mosaic-v1`, `packet-weave-v1`). The newest eight cover parser,
state-machine, data-structure, graph-routing, tagged-ledger, S-box, bit-matrix
and packet-framing families.

Level 1 decoys are the default and remain deliberately weak: they slow down
naive triage and give the benchmark ground truth, but they are ineffective
against an analyst holding the source. Levels 2/3 (input-driven live split,
bogus edges, volatile-state flattening) raise *static* reconstruction cost and
are off by default; they are not the threat model's Tier 2/3. **No protection
effectiveness has been measured, and none is claimed.**

## Optional model research

The model harness remains usable, but it is deliberately outside the normal
release loop. It is appropriate when there is a narrow question such as
"does this profile increase metered token cost on one calibrated task?" and
inappropriate as a recurring AI-versus-AI ritual.

Published pilots are retained as historical research. The latest dual-model
N=5 run measured descriptive token floors of 2.15× and 3.03× on one task, with
success changing from 2/5 to 1/5 and 0/5. It did not hold success fixed and is
not an effectiveness claim. No new model matrix is required to develop, test or
release the deterministic scorecard.

Task calibration distinguishes screening from comparison evidence. The six
remaining binary-recovery tasks have explicit `uncalibrated` records for both
pilot models; `delta-ledger-v1`, `sbox-cascade-v1`, `bit-mosaic-v1` and
`packet-weave-v1` have N=1 screening records only. Only `packed-record-v1` has
N=5 records for both `deepseek-v4-pro` and `deepseek-flash`, both at 0.4 and
marked `comparison-ready`. An N=1 screening label is never described as N=5.

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
level-3 flattening of `indirectbr`/`callbr`/coroutine/EH/`returns_twice`/
convergent constructs — is rejected with a clear error rather than
half-supported. Full matrix and
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

Eight suites: `aegis-policy`, `aegis-decoys`, `aegis-controlflow`,
`differential` (eight build profiles × 235 corpus cases),
`differential-representative` (four profiles over a 1 MiB minimum-work
algorithm workload), `protection-scorecard` (fixture regression budgets),
`protection-scorecard-representative` (calibrated workload budgets), and
`aegis-bench` (offline harness tests, no model, network or credentials).

## Protection scorecard

The default validation path is deterministic:

```bash
python3 tests/differential/run.py \
  --plugin build/lib/AegisPass.so \
  --report build/differential-report.json

cd tools/aegis-bench
python3 -m aegis_bench scorecard \
  --differential ../../build/differential-report.json \
  --budgets ../../experiments/protection-budgets.json \
  --out ../../build/scorecard
```

The small fixture gates the default profile at `.text` <= 25%, paired relative
p95 <= 25% and build-time growth <= 25%. The representative workload has its
own calibrated default gate: `.text` <= 30%, paired relative p95 <= 25% and
build-time growth <= 30%. Build comparisons use the median of three
independent clean builds. Details and limitations:
[`docs/protection-scorecard.md`](docs/protection-scorecard.md). Final
clean-tree evidence is in
[`docs/reports/harness-validation-final/`](docs/reports/harness-validation-final/README.md).

## Optional model research

```bash
cd tools/aegis-bench
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --task rolling-token-v2 --adapter ground-truth --profile baseline \
    --out /tmp/bench
# multi-cell model runs:
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
    --experiment ../../experiments/offline-smoke.json
```

This path is optional and is not run for ordinary releases. Real runs pass an
adapter from outside this repository, so no vendor SDK or API key enters the
tree or CI; run it with only the workspace mounted.
`aegis-bench campaign` owns the matrix, interleaves repetitions, writes
atomically after every cell and resumes from the raw JSONL. `aegis-bench
audit` checks duplicate/missing cells, stale task hashes, mixed meter
provenance and campaign fingerprints. Tokens are provider-measured when
`--meter-upstream` is used and otherwise adapter self-reports. Tool calls are
measured by the per-cell loopback broker when the adapter uses it; a bypass
shows `tools.requests: 0`. Oracle queries are counted by the harness broker
(and capped when a task sets `budgets.oracle_queries`). Report pass rates carry
Wilson 95% intervals, and cost deltas get an interval only when both sides have
at least two runs.
Protocol:
[`docs/benchmark-protocol.md`](docs/benchmark-protocol.md); harness:
[`tools/aegis-bench/README.md`](tools/aegis-bench/README.md); campaign and
audit contract: [`docs/campaigns.md`](docs/campaigns.md); process/tool
isolation design: [`docs/isolation.md`](docs/isolation.md).

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
- benchmark tool calls are broker-measured for mediated requests, but an
  in-process adapter can bypass the broker; tokens are provider-measured only
  when the meter is used, and otherwise self-reported. Oracle queries are
  counted by the broker. Optional Linux worker sandboxes use Landlock,
  seccomp and a private network namespace;
- `aegis-debug` (unprotected `-O0 -g`) is the supported way to debug a
  protected program — not the protected build itself.

## Layout

```text
aegis-ir/
├── include/aegis/        # public headers (version, policy)
├── lib/                  # LLVM pass plugin sources
├── tools/aegis-bench/    # benchmark harness (main product)
├── benchmarks/           # self-authored benchmark tasks
├── experiments/          # campaign manifests and offline smoke configuration
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
