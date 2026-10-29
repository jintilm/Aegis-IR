# Decoy transform (`aegis-decoys`)

Stage 4 adds the first transform that changes the emitted binary, plus a
verification gate that turns silent optimizer degradation into a build
failure.

```
aegis-policy<policy=...>,aegis-decoys,default<O2>,aegis-verify
```

## What it does

For every function the policy marks `level >= 1`, `aegis-decoys`:

1. splits the entry block after allocas and PHIs;
2. inserts a branch guarded by a volatile load of `@__aegis.guard`
   (internal, zero initialised, never stored to);
3. fills the statically-present but dynamically-dead arm with calls to
   plausible-looking decoy functions and an `unreachable`;
4. leaves the original body reachable through the other arm.

The module also gets 4–6 decoy functions and one decoy string each, both drawn
from a curated in-tree corpus by a deterministic splitmix64 plan seeded from
`aegis.seed`.

## Why the decoy branch is dead by construction

The guard is internal, zero-initialised, and the verifier rejects any use of it
other than a volatile load. Nothing in the module can write to it, so the
branch condition is always false at run time. Semantics are therefore
unchanged by construction, not by testing — the differential matrix checks the
claim empirically, but the argument does not depend on it.

`volatile` matters for the same reason it does for the decoy strings: it is the
one load the optimizer may not fold or reuse.

## The verifier is the point

`aegis-verify` runs after `default<O2>` and fails the build when:

| check | failure it catches |
| --- | --- |
| every planned decoy function present (by metadata) | GlobalDCE/Internalize removing the decoys |
| enough globals carry `aegis.decoy.str` | the optimizer dropping decoy strings |
| guard exists, internal, zero-initialised, never stored | a transform bug making the branch live |
| every recorded guarded function keeps a guard load **and** a decoy call | the branch being erased |
| total volatile guard loads >= guarded functions | inlining that lost a copy |
| every `level >= 1` function was in fact guarded | passes run out of order |

Fail-closed is deliberate: a build whose protection silently degraded must not
ship. The cost is that a genuine improvement in the optimizer (say, a future
proof that the branch is dead) shows up as a build failure rather than a quiet
loss of protection — which is the correct signal for this project.

## Pipeline ordering is a hard requirement

The transform must see **frontend IR**:

```bash
clang++ -O2 -Xclang -disable-llvm-passes -S -emit-llvm input.cpp -o input.ll
opt -load-pass-plugin=build/lib/AegisPass.so \
    -passes='aegis-policy<policy=p.json>,aegis-decoys,default<O2>,aegis-verify' \
    input.ll -S -o protected.ll
```

This is not stylistic. `clang -O2 -emit-llvm` has already run the inliner, so a
small function the policy selects may exist only as an inlined copy; guarding
it decorates dead IR. The verifier catches exactly this and fails with
`volatile guard load(s) ... decoy branch was erased`, which is the symptom of
running the Aegis passes too late.

## Determinism

The plan is a pure function of `aegis.seed`: same seed, byte-identical IR;
different seed, different function names, strings, and call selection. No
timestamps, paths, or `std::hash` enter the plan. Two consequences worth being
explicit about:

- reproducible builds work;
- a per-release seed is the only knob controlling variety, so two builds with
  the same seed produce the same decoys — intentional, because the alternative
  (hidden per-build randomness) makes builds unreproducible and bug reports
  unactionable.

## What this does **not** do

Tier-1 honesty, stated plainly (see [`threat-model.md`](threat-model.md)):

- It does not hide that decoys exist. A C1 adversary reads the corpus in this
  repository and filters all of them. Decoys are effective against C0 effort
  and against tooling that ranks functions by plausibility without a ground
  truth; they are **not** effective against a competent analyst with the source.
- It does not change control flow in a way that survives a determined dynamic
  trace: the branch is never taken, so coverage-guided tooling prunes it
  immediately.
- It does not obscure the policy. `aegis.level` attributes and module flags are
  visible in the binary's metadata-free form only after stripping; a
  white-box adversary has the policy file.
- The decoy corpus is authored offline and reviewed in-tree. No LLM runs in
  the build path.

Treat decoys as a baseline that makes naive triage slower and gives the
benchmark a ground truth to measure "decoy identification rate" against — not
as an anti-analysis mechanism.

## Ground truth for the benchmark

`aegis-decoys` prints every artifact it created:

```
[aegis-decoys] decoy fn=... str="..."
[aegis-decoys] summary: seed=... guarded=N decoy_functions=M decoy_strings=M
```

`aegis-verify` prints what survived. These lines are the ground truth for the
Aegis-Bench metric *decoy identification rate*: a model or analyst claiming a
function is a decoy can be scored against the recorded set without guessing.

## Tests

`tests/decoys/run.sh` (CTest `aegis-decoys`) covers: artifacts surviving `-O2`,
the guard load surviving, the module still passing LLVM's verifier, level-0
functions untouched, the gate failing when `aegis-decoys` is skipped, the gate
failing on seed drift, byte-identical reproduction, seed sensitivity, guard
survival through inlining, and a non-volatile-guard negative control.

`tests/differential/` runs both protected profiles through the full pipeline
and reports `.text`/`.data` growth next to the size and p95-time baseline.
