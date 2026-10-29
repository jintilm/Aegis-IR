# Claims ledger

Every public claim about protection effectiveness lives here, one row per
claim, each pointing at a reproducible report. If a claim is not in this
ledger, it must not appear in README, release notes, or talks.

| Claim ID | Statement (exact wording used publicly) | Evidence (report path / commit / date) | Model versions | Scope (attacker class, task set) |
|---|---|---|---|---|
| C-001 | "Tier-1 decoys change the protected fixture's `.text` from 5023 to 6132 bytes (+22.1%) while producing byte-identical program output and exit codes on all 235 differential corpus cases." | `tests/differential` report (`build/differential-report.json`, commit tagged at stage 4, 2026-10-29); fixture = offline C++ algorithm library | LLVM/Clang 23.1.5 | correctness/cost only; **no adversarial claim**. C0–C4 effectiveness is untested until the Aegis-Bench harness lands |
| C-002 | "The verify gate fails the build when the decoy transform is skipped, when the seed drifts from the transform, and when a guard load loses its `volatile` marker." | `tests/decoys/run.sh` (CTest `aegis-decoys`), stage 4 | n/a | build-gate behaviour, not protection strength |

Deliberately **not** claimed at this stage: that decoys slow down or defeat
any attacker class. Tier-1 decoys are structurally ineffective against a
white-box adversary reading the corpus; see [`decoys.md`](decoys.md).

Rules:

1. Claims are about **cost deltas at a fixed success criterion**, never about
   "defeating AI".
2. Every claim states the attacker class (C0–C4) and task-set version; claims
   that aggregate classes must publish the per-class breakdown.
3. Negative results go in the ledger too, with the same prominence.