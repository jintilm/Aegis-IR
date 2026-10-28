# Architecture

Status: working draft. Describes the intended shape; only the audit pass
exists in code today.

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
- Insertion happens after inlining decisions; behaviour under `-O0`, `-O2`
  and LTO is defined in the compatibility matrix (to be written).

## Build profiles

Five artifacts enter the differential test matrix:

| Profile | Transforms | Symbols | Purpose |
|---|---|---|---|
| `baseline` | none | full | reference behaviour |
| `release` | none | stripped | fair comparison baseline |
| `aegis-standard` | Tier 1 (default) | stripped | shipped protection |
| `aegis-research` | experimental; off by default | stripped | research features |
| `aegis-debug` | none | full | supported debugging of protected programs |

The `aegis-debug` profile is the official answer to "obfuscation broke my
production debugging": rebuild the same commit with it, reproduce, fix.

## Aegis-Bench

- **Harness** (`tools/aegis-bench/`): Python; agent adapters, task runner,
  independent grader, report generator. Fixed budgets (model version, prompt,
  tool set, timeouts, token caps) are recorded per run.
- **Tasks** (`benchmarks/`): self-authored C/C++ programs only. Each task has
  ground-truth source, executable property tests, and hidden edge cases.
  Private scoring set is rotated quarterly and stored separately from the
  public tasks.
- **Scoring**: re-executability against hidden property tests, differential
  fuzzing against ground truth, and a double-blind rubric for descriptive
  answers. Text similarity is never a primary metric.
- **Red teams**: C1 static, C2 dynamic, C3 symbolic-assisted, plus a
  *white-box* attacker holding this source code and training decoy filters.
  The white-box attacker is the honest control.

## Boundaries

- The obfuscator never contacts the network at build time (reproducible
  builds; LLM-generated decoy templates are curated offline and committed).
- The benchmark never ships model API keys; private results are published
  with model/version stamps so third parties can interpret decay curves.