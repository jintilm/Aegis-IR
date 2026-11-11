# Claims ledger

Every public claim about protection effectiveness lives here, one row per
claim, each pointing at a reproducible report. If a claim is not in this
ledger, it must not appear in README, release notes, or talks.

| Claim ID | Statement (exact wording used publicly) | Evidence (report path / commit / date) | Model versions | Scope (attacker class, task set) |
|---|---|---|---|---|
| C-001 | "Tier-1 decoys change the protected fixture's `.text` from 5023 to 6132 bytes (+22.1%) while producing byte-identical program output and exit codes on all 235 differential corpus cases." | `tests/differential` report (`docs/reports/archive/v0.1.0-alpha/differential-report.json`, frozen at `v0.1.0-alpha`); fixture = offline C++ algorithm library | LLVM/Clang 23.1.5 | correctness/cost only; **no adversarial claim**. C0–C4 effectiveness is untested until the Aegis-Bench harness lands |
| C-002 | "The verify gate fails the build when the decoy transform is skipped, when the seed drifts from the transform, and when a guard load loses its `volatile` marker." | `tests/decoys/run.sh` (CTest `aegis-decoys`), stage 4 | n/a | build-gate behaviour, not protection strength |
| C-003 | "Level-2 control-flow transforms change the protected fixture's `.text` from 5023 to 5672 bytes (+12.9%) while producing byte-identical program output and exit codes on all 235 differential corpus cases." | `docs/reports/harness-validation/differential-report.json`, `aegis-research` profile (seed 777), main after `v0.1.0-alpha` | LLVM/Clang 23.1.5 | correctness/cost only; synthetic fixture; **no adversarial claim** |
| C-004 | "Level-3 flattening changes the protected fixture's `.text` from 5023 to 6642 bytes (+32.2%) while producing byte-identical program output and exit codes on all 235 differential corpus cases." | `docs/reports/harness-validation/differential-report.json`, `aegis-flattened` profile (seed 778), main after `v0.1.0-alpha` | LLVM/Clang 23.1.5 | correctness/cost only; synthetic fixture; **no adversarial claim** |
| C-005 | "The verify gate fails the build when `aegis-cff` is skipped for a level>=2 function, when the dispatcher state or salt load loses `volatile`, when the dispatcher no longer derives from the volatile state load, when a level-2 bogus arm is made live, and when level 3 is requested for an `indirectbr` function." | `tests/controlflow/run.sh` (CTest `aegis-controlflow`), main after `v0.1.0-alpha` | n/a | build-gate behaviour, not protection strength |

The level-2 and level-3 profiles use different seeds (777/778), so C-003 and
C-004 are each comparable to the shared baseline, not to each other as a
monotonic ladder.

Deliberately **not** claimed at this stage: that decoys, bogus flow or
flattening slow down or defeat any attacker class. Tier-1 decoys are
structurally ineffective against a white-box adversary reading the corpus, and
the flattening dispatcher is plainly visible to dynamic tracing; the state
encoding key derives from the shipped seed. See [`decoys.md`](decoys.md) and
[`controlflow.md`](controlflow.md).

Also not claimed, and now explained rather than merely observed: the first
real-model pilot ([`reports/pilot-2026-11-11/`](reports/pilot-2026-11-11/README.md))
measured a level-3-vs-baseline delta of about zero, and it *had* to. That run
used `oracle` access: the agent's workspace held a counted shim whose behaviour
is identical in every artifact profile, so the protection had nothing to act
on. The number is real, the design could not have produced any other, and it is
not evidence either way. A protection comparison requires `binary` access —
see [`benchmark-protocol.md`](benchmark-protocol.md#access-modes).

The second pilot ([`reports/pilot-2026-11-12-binary/`](reports/pilot-2026-11-12-binary/README.md))
does use `binary` access and does find a token-cost increase (~+90% at N=2).
It is still not a claim: N=2, one task, one model, baseline at the ceiling, a
wall-clock effect pointing the other way, and a disassembler-only adversary.
It is the shape of the measurement the project exists to make; it is not
evidence until the matrix in the protocol says so.

Rules:

1. Claims are about **cost deltas at a fixed success criterion**, never about
   "defeating AI".
2. Every claim states the attacker class (C0–C4) and task-set version; claims
   that aggregate classes must publish the per-class breakdown.
3. Negative results go in the ledger too, with the same prominence.