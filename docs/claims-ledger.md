# Claims ledger

Every public claim about protection effectiveness lives here, one row per
claim, each pointing at a reproducible report. If a claim is not in this
ledger, it must not appear in README, release notes, or talks.

| Claim ID | Statement (exact wording used publicly) | Evidence (report path / commit / date) | Model versions | Scope (attacker class, task set) |
|---|---|---|---|---|
| — | *(no claims yet; first entries arrive with the v0.2 benchmark report)* | | | |

Rules:

1. Claims are about **cost deltas at a fixed success criterion**, never about
   "defeating AI".
2. Every claim states the attacker class (C0–C4) and task-set version; claims
   that aggregate classes must publish the per-class breakdown.
3. Negative results go in the ledger too, with the same prominence.