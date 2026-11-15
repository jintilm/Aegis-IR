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
| C-006 | "On `packed-record-v1` under binary access and sandboxed N=5, level-3 provider-metered token floors were 2.15× baseline for `deepseek-v4-pro` (909,318 vs 422,646 mean tokens) and 3.03× for `deepseek-flash` (636,195 vs 210,224); observed pass counts were 2/5→1/5 and 2/5→0/5. The token totals exclude 125 abandoned calls without usage, success was not held fixed, and this is not an effectiveness claim." | `docs/reports/pilot-2026-11-13-dual-model-n5/`, source commit `7b2ba67`, 2026-11-13 | `deepseek-v4-pro`, `deepseek-flash` via the reference adapter source hash `3cfa0466724c` | C2 binary-recovery agent; one task, one step budget, two configurations; **descriptive cost only** |
| C-007 | "On the self-authored representative workload with at least 1 MiB of work per invocation, `aegis-standard` produced zero mismatches over 75 cases and passed its calibrated default gate: `.text` 7689→9268 bytes (+20.5%), paired relative p95 +18.4%, and build median +9.7% with three profile-interleaved samples per arm. These are synthetic engineering regression numbers, not production-performance or attack-effectiveness claims." | `docs/reports/harness-validation-v0.4.0-alpha/scorecard-representative/`, source commit `e00437e`, 2026-11-15 | n/a (offline deterministic adapters) | LLVM/Clang 23.1.5; self-authored representative workload; performance/correctness engineering only; **no adversarial claim** |
| C-008 | "On the pinned Unlicense `kokke/tiny-AES-c` commit `2385675`, an AES-128 ECB wrapper produced zero mismatches and zero sanitizer/property failures over 75 deterministic cases in baseline, standard, standard+LTO, research and flattened profiles. `aegis-standard` changed `.text` from 8816 to 10065 bytes (+14.17%) with paired relative p95 +20.92%; `aegis-standard-lto` produced 5708 bytes with paired relative p95 +16.47%. These are external compatibility and engineering regression numbers, not production-performance or attack-effectiveness claims." | `docs/reports/external-tiny-aes-c-2385675/`, source commit `2c7c49c`, 2026-11-15 | n/a (offline deterministic adapters) | LLVM/Clang 23.1.5; one pinned public-domain C implementation; **no adversarial claim** |

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

The second pilots use `binary` access and do find a cost signal, but not a
stable success signal: at N=2 both profiles passed, and the N=5 rerun
([`reports/pilot-2026-11-12-binary-n5/`](reports/pilot-2026-11-12-binary-n5/README.md))
did not reproduce that — baseline 1/5, level 3 0/5, with the binding
constraint being whether the agent submits at all. A fourth run
([`reports/pilot-2026-11-12-binary-cost/`](reports/pilot-2026-11-12-binary-cost/README.md))
gave every run a cost by adding a tool-free final turn, and the cost ratio then
replicated: level 3 over baseline **1.91×, 2.06×, 2.12×** tokens in three
30-step runs, 2.05× pooled (457 k vs 935 k).

The ratio is not a claim, and the protocol now says why in numbers: success is
a Bernoulli per run, the pooled difference is 3/12 vs 2/11 (Fisher p = 0.55),
and resolving it would take ~540 runs per arm — or ~100 if the 45-step arm is
pooled instead, which is itself the reason no direction is asserted. Pooling
runs that differ only in step budget moves the estimate nine points. **The
success-rate effect is therefore unmeasured, not absent**, and no report may
describe protection as reducing recovery success. The cost ratio is reported as
a magnitude on one task, one model, one attacker class, and a linear
disassembler without a decompiler — not as an effectiveness result.

Those pilots also predate harness-owned token metering, so their token figures
are adapter self-reports. `--meter-upstream` now puts a loopback proxy in front
of the model endpoint and records the provider's own `usage` report, which is
what a published cost figure has to rest on
([protocol](benchmark-protocol.md#token-metering)). Any future ratio is quoted
from metered rows; a ratio pooled across metered and self-reported rows is not
admissible.

The final dual-model pilot
([`reports/pilot-2026-11-13-dual-model-n5/`](reports/pilot-2026-11-13-dual-model-n5/README.md))
puts both `deepseek-v4-pro` and `deepseek-flash` in one 20-cell campaign under
binary access, process isolation, Landlock/seccomp, a private network
namespace, the harness tool broker and the meter. Baseline/level-3 pass counts
were 2/5→1/5 for pro and 2/5→0/5 for flash. Provider-metered token floors were
422,646→909,318 (**2.15×**) and 210,224→636,195 (**3.03×**). This does **not**
enter the ledger as an effectiveness claim: the arms did not hold success
fixed, the totals exclude 125 abandoned calls without usage, and the pass-count
difference at N=5 is not powered. The report is methodological evidence that
the dual-model, metered and isolated path works.

C-007 and C-008 are deliberately separate from protection effectiveness. They
record calibrated deterministic engineering results on synthetic and pinned
external workloads with full machine-readable artifacts. Research-profile
observations are reported but do not block release.

Rules:

1. Claims are about **cost deltas at a fixed success criterion**, never about
   "defeating AI".
2. Every claim states the attacker class (C0–C4) and task-set version; claims
   that aggregate classes must publish the per-class breakdown.
3. Negative results go in the ledger too, with the same prominence.
