# Threat model

Status: working draft, v0. Expected to change as benchmark data arrives.

## 1. What we protect

Assets, in decreasing order of how well local protection can serve them:

1. **Entitlement enforcement** — ensuring only licensed deployments get correct
   results. Served by key binding, activation, and watermarking (see the
   long-term plan in the internal design doc), not by obfuscation alone.
2. **Implementation secrecy** — raising the cost of recovering an algorithm's
   semantics from a shipped binary or library. Served by this project's
   transforms, with explicit limits below.
3. **Provenance** — the ability to trace a leaked build back to a licensee.
   Served by per-license watermarks.

## 2. Attacker capability classes

The threat model targets *pipelines*, not models. A pipeline is a person plus
one or more LLM/agent instances plus tooling.

| Class | Capability | Notes |
|---|---|---|
| C0 | LLM reading decompiled pseudo-code, no tools | cheapest attacker |
| C1 | Static toolchain + LLM orchestration (Ghidra/IDA via MCP, strings, xrefs, call graphs) | the class most affected by decoys |
| C2 | C1 + dynamic tracing (Frida/ptrace, coverage, differential execution, time-travel debugging) | prunes never-executed decoys wholesale |
| C3 | C2 + automated program analysis (symbolic execution, taint, constraint solving, differential fuzzing) | most local protections reduce to cost, not prevention |
| C4 | Human expert + AI assistance | long-run; we only ever aim to raise cost |

A benchmark run states which of these it models through its **access mode**
([`benchmark-protocol.md`](benchmark-protocol.md#access-modes)). `oracle`
access — a counted I/O oracle, no artifact — is weaker than C0 for the purposes
of protection: it cannot see code at all, so a transform has nothing to act on
and a level-vs-baseline delta is zero by construction. `binary` access (a
stripped probe plus a linear disassembler) sits between C1 and C2: it has the
artifact and can execute it, but not a decompiler, a scripting layer or tracing
tools.

## 3. Protection tiers and expected effect

| Tier | Mechanism family | Semantics | Expected effect by attacker class |
|---|---|---|---|
| 0 | none | — | baseline |
| 1 | static-cost: string/name/structural decoys, dead-path honey pots, symbol hygiene | preserved; decoys never execute | C0/C1: strong. C2: mostly lost to coverage pruning. C3: negligible. |
| 2 | execution-cost: cold-path mounting, timing dependence, data-driven dispatch | preserved (I/O equivalent), but observability depends on runtime conditions | C2: meaningful. C3: marginal. Higher maintenance cost; disabled by default. |
| 3 | semantics removal: cloud/TEE participation | *changes* the observable contract | architectural migration, out of scope for the obfuscator, recommended as guidance |

We publish this table in every benchmark report. A transform that only moves
the cost for C1 must say so.

### Policy levels are not tier numbers

The policy file's `level` field is a transform-strength knob, not a claim that
a module implements the threat-model tier of the same number:

| Policy level | What ships | Tier family |
|---|---|---|
| 1 | decoys, dead paths, symbol/string bait | Tier 1 |
| 2 | level 1 + input-driven live split + bogus edges | local static cost; the live split makes the executed path input-dependent, but the observable contract is unchanged |
| 3 | level 2 + volatile-state-machine flattening | local static cost; no loader, no timing dependence |

None of these implements the Tier-2 mechanism family in the table above (cold-
path mounting with a loader, timing dependence, runtime-conditioned
observability), and none performs Tier-3 semantics removal. Levels 2/3 remain
compile-time, semantics-preserving transforms; expect the same coverage-guided
pruning against C2+ that Tier 1 suffers, with a higher static reconstruction
cost. The distinction is deliberate: it prevents "level 3" from being read as
"Tier 3" in a sales conversation. See [`controlflow.md`](controlflow.md).

## 4. Assumptions and hard bounds

- **White-box assumption (Kerckhoffs).** The adversary has this source code,
  can build it, and can train decoy filters against it. Security therefore
  rests on per-build seeding and template rotation, never on transform
  secrecy.
- **Oracle access.** Attackers can call protected code as a black box. For
  pure functions with small input domains, black-box recovery is feasible
  regardless of obfuscation strength. The honest goal is therefore detect-
  and-trace plus cost inflation, not prevention.
- **Impossibility bound.** No semantics-preserving transform resists an
  adversary with unbounded queries (Barak et al., CRYPTO 2001). All claims in
  this project are cost claims, stated with model version and date.
- **Model drift.** Claims age as agents improve. Benchmark reports carry
  timestamps and model versions; periodic re-runs are part of the protocol.

## 5. Non-goals (permanent)

- Sandbox/analysis-environment detection that changes business results.
- Anti-debugging that causes incorrect behavior or crashes.
- SMC/JIT self-modifying code as a default profile.
- Any feature whose primary purpose is evading malware analysis.

## 6. Trust boundary notes

- Client-side obfuscation is not a secret-store. Long-lived keys do not belong
  in client binaries.
- Integrity signals may inform risk decisions but never replace server-side
  authentication and authorization.
- Debug/diagnostic capability must be explicit, authorized, and auditable —
  never a hidden permanent backdoor. See the `aegis-debug` build profile in
  `docs/architecture.md`.