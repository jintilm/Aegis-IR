# Control-flow transforms (`aegis-cff`)

Levels 2 and 3 add local control-flow cost on top of the Tier-1 decoys. Both
remain **semantics-preserving by construction**: program output and exit codes
are identical to an unprotected build, which the differential matrix checks on
every corpus case.

```
aegis-policy<policy=...>,aegis-decoys,aegis-cff,default<O2>,aegis-verify
```

`aegis-cff` requires `aegis-decoys` to have run first (it builds the live split
on the decoy guard branch); it fails the build rather than silently skipping if
the guard or decoy functions are missing.

## Level 2 — bogus flow plus an input-driven live split

For every function the policy marks `level >= 2`:

1. **Live split.** The decoy guard's body edge is routed through a fresh block
   whose branch condition is derived from a function argument (integers
   directly, pointers via `ptrtoint`). Both arms perform volatile loads of
   `@__aegis.guard` / `@__aegis.cff.salt` and rejoin the body. The program
   results do not depend on the arm, but the **executed path does depend on the
   input** — a dynamic trace of two different inputs is not identical.
   Functions without an integer or pointer argument fall back to a
   salt-based predicate; the split survives, but it is statically dead, and
   the docs say so rather than pretending otherwise.
2. **Bogus edges.** One or two blocks deeper in the function get a second
   opaque predicate: `volatile load @__aegis.cff.salt != 0` selects a junk
   arm, which makes plausible calls into the decoy set and ends in
   `unreachable`. The salt is internal, zero-initialised and never stored to,
   so the arm is dynamically dead.

The arms of the live split deliberately perform **different numbers of
volatile accesses**. When both arms consisted of one load, LLVM folded them
into a select of pointers plus one load; the differing access counts keep the
branch. Both globals remain zero, so the merge is semantically irrelevant, but
the branch is what level 2 is for.

## Level 3 — flattening into a volatile state machine

Level 3 includes level 2 and then flattens the function:

1. **All PHIs and all cross-block SSA values are demoted to stack slots.**
   Giving the dispatcher an edge to every case block breaks the static
   dominance relations that made those values legal. This is not optional;
   without it the LLVM verifier rejects the module.
2. Static allocas move to a new entry block, which also holds an `i32` state
   slot.
3. Every `br` becomes a volatile state store plus a jump to a dispatcher;
   conditional branches become a `select` of two encoded states. `switch`
   edges are retargeted to trampoline blocks that store the state.
4. The dispatcher loads the state **volatile**, XORs it with a salt-derived key
   (zero at run time by the salt invariant), and `switch`es to the case block.
   State indices are encoded with a seed-derived key, so the case constants
   do not read as block numbers.

The volatile state is the load-bearing detail: without it `mem2reg`/SROA would
turn the state machine back into PHIs, constant-fold the dispatcher, and
recover the original CFG at `-O2`. The verifier rejects a build where the
state access lost its `volatile` marker.

### Cost

Flattening is not free and not for hot paths. On the differential fixture
(small functions, 235 cases), `.text` grows from 5023 to 6642 bytes (+32.3%)
for level 3 and 5672 bytes (+12.9%) for level 2; every function also pays a
volatile load and store per basic block. Measured numbers and scope:
[`claims-ledger.md`](claims-ledger.md) C-003/C-004.

## Verification

`aegis-verify` runs after `default<O2>`. For level 2/3 it requires:

| check | failure it catches |
| --- | --- |
| salt global exists, internal, zero-initialised, only volatile reads | a transform bug or optimizer change making the predicates live |
| every recorded level-2 function has a volatile salt load feeding a branch whose arm ends in `unreachable` | an opaque edge was erased, or the load survived while the edge did not |
| total salt loads >= number of level-2 functions | inlining/erasure lost an edge |
| every recorded level-3 function still has an `i32` alloca with a volatile load **and** store | mem2reg/SROA recovered the CFG |
| the dispatcher `switch` condition is derived from a volatile load in its own block | the switch survived but no longer selects on the state (a constant-folded dispatcher) |
| total state slots >= number of flattened functions | a state machine was erased |
| every level>=2 function with the attribute is in the recorded set | `aegis-cff` skipped or run out of order |

The salt check follows `select`/`GEP`/`bitcast` chains, because the optimizer
is allowed to fold two volatile loads of different zero globals into a select
of pointers and one load. What it may not do is store to them.

## Fail-loud eligibility

Level 3 selection of a construct the rewrite cannot handle **fails the build**
with the reason, instead of leaving the function partially transformed:

- `indirectbr` (computed goto) and `callbr`;
- exception-handling terminators (`invoke`, `catchswitch`, `cleanupret`, …);
- coroutines, GC statepoints, stackmap/patchpoint and `llvm.experimental.
  deoptimize` intrinsics;
- inline assembly and calls to `convergent` functions;
- functions that call a `returns_twice` function (`setjmp`/`longjmp`), where a
  second entry into the body would skip the dispatcher prologue;
- the base rules shared with decoys: `optnone`, `naked`,
  `available_externally`, an EH personality, `musttail`.

Level 2 only needs the base rules.

## What this does **not** do

Stated plainly, because the tier names invite over-reading:

- **It is not the threat model's Tier 2.** There is no loader, no timing
  dependence and no runtime-conditioned business behavior; the live split's
  path depends on the input, but the observable contract is unchanged. Both
  levels are compile-time, semantics-preserving transforms.
- **It is not Tier 3.** Semantics removal (cloud/TEE participation) is an
  architectural migration and out of scope for this plugin.
- **It does not hide the dispatcher from dynamic tracing.** A C2 analyst sees
  the volatile state slot and the dispatch loop immediately; the transform
  raises *static* reconstruction cost, and the docs do not claim more.
- **It does not survive a white-box analyst with the source and this
  document.** The state encoding key is derived from the shipped seed, and the
  algorithm is public. Kerckhoffs applies.
- **It has no measured adversarial effect.** No model has been run against
  these levels. See the claims ledger for the exact scope of every number.

## Determinism

Every artifact derives from `aegis.seed`: decoy corpus, bogus-edge selection,
the state-encoding key, and the salt. Two builds with the same policy and seed
produce byte-identical IR (tested). No timestamps or paths enter the
transform.

## Tests

`tests/controlflow/run.sh` (CTest `aegis-controlflow`) covers: level 2/3
pipelines building and verifying, salt loads and state slots surviving `-O2`,
byte-identical output against baseline on the fixture, determinism, PHI
demotion on a hand-written IR fixture, the gate failing when `aegis-cff` is
skipped, when the state or salt loses `volatile`, when the dispatcher is
detached from the state load, when a level-2 bogus arm is made live, when
decoys are skipped, and when level 3 is requested for an `indirectbr`
function. The differential matrix
adds level-2 (`aegis-research`) and level-3 (`aegis-flattened`) profiles over
the 235-case corpus.
