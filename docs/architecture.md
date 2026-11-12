# Architecture

Status: working draft. The audit, lint, policy, decoy, control-flow and verify
passes exist in code; further transforms are sketches.

## Components

```text
                     policy (aegis-policy.json)
                                   │
                                   ▼
   source ──► clang ──► LLVM IR ──► aegis-policy ──► [aegis transforms] ──► verifier ──► object
                          │        (attrs: aegis.level)
                          │        (flags: aegis.profile, aegis.seed)
                          └──► selection report (matched / skipped / errors)

   aegis-bench (main product)
   ├── harness   — agent adapters (C1–C3 red teams), runner, budget control
   ├── artifacts — stripped probe per protection profile (levels 0–3)
   ├── tasks     — self-authored fixtures + ground truth + property tests
   └── protocol  — scoring rules, private-set custody, drift reports
```

## Policy flow

`aegis-policy` runs first on freshly emitted IR and resolves entries against
symbol names exactly once; the decision is pinned onto functions as
`aegis.level` attributes and module flags. Every later transform reads only
the attributes, so selection survives inlining, renaming and LTO. Unresolved
entries fail the build. Details: [`policy.md`](policy.md).

## Pass plugin

- New Pass Manager plugin, loaded with `-load-pass-plugin`.
- Selection is driven by function attributes (`aegis.level`) written by a
  small Clang-compatible annotation or a policy JSON lowered to attributes;
  name matching alone is not LTO-safe.
- Every transform ships with a verifier. A failed verification fails the
  build; decoys that were optimised away are build errors, not warnings.
- The passes run on **frontend IR**, before `default<O2>`: a `-O2 -emit-llvm`
  module is already inlined, and guarding there decorates dead IR (the
  verifier rejects it). Defined compatibility with `-O0`, `-O2` and LTO is
  the job of the compatibility matrix (to be written).
- The current transform set is policy selection, Tier-1 decoys (`aegis-decoys`)
  and the level 2/3 control-flow transforms (`aegis-cff`: bogus flow, live
  split, flattening), all gated by `aegis-verify`. `aegis-lint` is the
  read-only preflight for the same eligibility rules. See
  [`decoys.md`](decoys.md) and [`controlflow.md`](controlflow.md).

## Build profiles

Eight artifacts enter the differential test matrix (see
[`build-profiles.md`](build-profiles.md) for flags and the runner):

| Profile | Transforms | Symbols | Purpose |
|---|---|---|---|
| `baseline` | none | full | reference behaviour |
| `release` | none | stripped | fair comparison baseline |
| `release-opt` | bare `default<O2>` via `opt` | stripped | isolates `opt` round-trip from protection |
| `aegis-standard` | policy level 1 + decoys + verify | stripped | shipped protection |
| `aegis-research` | policy level 2 + decoys + cff + verify | stripped | live split + bogus edges |
| `aegis-flattened` | policy level 3 + decoys + cff + verify | stripped | control-flow flattening |
| `aegis-debug` | none | full | supported debugging of protected programs |
| `baseline-asan` | none, ASan+UBSan | full | safety net over the corpus |

The `aegis-debug` profile is the official answer to "obfuscation broke my
production debugging": rebuild the same commit with it, reproduce, fix.

## Aegis-Bench

- **Harness** (`tools/aegis-bench/`): Python; agent adapters, task runner,
  resumable campaign planner, independent JSONL auditor, grader and report
  generator. Fixed budgets (model version, prompt, tool set, timeouts, token
  caps) are recorded per run. Task schema v2 records the declared tool policy,
  input domain, experiment use and difficulty in every row.
- **Tasks** (`benchmarks/`): self-authored C/C++ programs only. Tasks are
  either `reimplement` (brief + examples) or `binary-recovery` (a stripped
  probe built from ground truth at protection levels 0–3). Each task has
  ground-truth source, executable property tests, hidden edge cases, and a
  manifest that pins a content hash and the artifact recipe. Private scoring
  set is rotated quarterly and stored separately from the public tasks.
- **Scoring**: re-executability against hidden property tests, differential
  fuzzing against ground truth, and a double-blind rubric for descriptive
  answers. Text similarity is never a primary metric.
- **Red teams**: C1 static, C2 dynamic, C3 symbolic-assisted, plus a
  *white-box* attacker holding this source code and training decoy filters.
  The white-box attacker is the honest control.
- **Campaign boundary**: the campaign and atomic checkpoint are implemented.
  A per-cell loopback tool broker enforces the declared tool surface, call
  budget and workspace containment for mediated calls. Campaigns may run the
  adapter in a fresh subprocess with a workspace-only TaskView. That process
  boundary can still reach host paths and networks, so filesystem/network
  isolation remains specified in [`isolation.md`](isolation.md) and is
  required before a protection-effect claim.

## Boundaries

- The obfuscator never contacts the network at build time (reproducible
  builds; LLM-generated decoy templates are curated offline and committed).
- The benchmark never ships model API keys; private results are published
  with model/version stamps so third parties can interpret decay curves.
