# Policy reference

The policy file is the single source of truth for which functions are
protected. It is parsed once by the `aegis-policy` pass, which lowers it to
IR attributes; downstream transforms never look at names again.

## Schema (v1)

```json
{
  "schema_version": 1,
  "profile": "release",
  "seed": 1234,
  "functions": [
    { "name": "_Z15transform_valuei", "level": 1, "reason": "benchmark fixture" }
  ],
  "limits": {
    "max_binary_growth_percent": 10,
    "max_p95_slowdown_percent": 5
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | integer | yes | currently only `1` |
| `profile` | string | yes | `dev` \| `release` \| `research` \| `debug` |
| `seed` | integer | no | `[0, 2^32-1]`; recorded as module flag for transforms |
| `functions` | array | yes | entries below; may be empty (protect nothing) |
| `functions[].name` | string | yes | symbol name, or demangled name (see matching) |
| `functions[].level` | integer | yes | `0` = explicitly unprotected; `1` = decoys, `2` = bogus flow + live split, `3` = level 2 + flattening (see below) |
| `functions[].reason` | string | no | shown in selection reports; strongly recommended |
| `limits.*` | integer | no | engineering budget targets, currently reported only |

Unknown top-level keys are ignored for forward compatibility.

## Levels and what is implemented

All levels `1..3` are implemented (`kMaxImplementedLevel` in
`lib/DecoyCorpus.h`). The level is a **transform-strength knob**, not the
threat model's tier number: levels 2/3 are still semantics-preserving,
compile-time transforms. Level 2 adds an input-driven live split and bogus
edges; level 3 adds control-flow flattening. Neither is the threat model's
Tier-2 "runtime-conditioned observability" mechanism family, and neither is
Tier 3 (semantics removal via cloud/TEE), which is out of scope for the
obfuscator. See [`controlflow.md`](controlflow.md) and
[`threat-model.md`](threat-model.md).

An entry above level 3 is rejected by the policy parser. A selected function
the transform cannot safely modify is a build error, never a silent skip,
because accepting it would ship a binary the policy claims is protected more
strongly than it is. Level 2 shares the base eligibility rules with decoys
(`optnone`, `naked`, exception-handling personality, `musttail`); level 3 also
rejects `indirectbr`, `callbr`, EH terminators and coroutines. See
[`compatibility.md`](compatibility.md) for the full list.

## Semantics

- Functions not listed are **not** protected (selection is explicit, never
  implicit scanning).
- An entry that does not resolve to a definition is a **build error**. A typo
  must not silently leave code unprotected.
- The policy is lowered to `aegis.level="<n>"` function attributes plus the
  `aegis.profile` / `aegis.seed` module flags. Transforms read the attribute,
  so protection survives inlining, symbol renaming and LTO.
- Any positive selection also records `aegis.protection.requested`. This
  durable module flag keeps the verifier fail-closed if optimization erases
  the selected definitions and their attributes before a transform runs.
- Empty selections and policies containing only level 0 pass the full
  transform/optimization/verification pipeline without adding protection
  artifacts. Existing positive requests or transform records still require
  verification; they cannot be cleared by a later empty selection.

## Name matching

1. **Exact symbol match** (preferred). C++ functions use their mangled names;
   get them from `llvm-nm`, `clang -S` output, or a selection report.
2. **Demangled fallback**: if no exact match exists, an entry is compared
   against `llvm::demangle()`. A bare name matches up to its parameter list —
   `transform_value` matches `transform_value(int)`. Overloads make this
   ambiguous and fail with a diagnostic asking for the mangled name.

## Pipeline placement

`aegis-policy` must run first, on freshly emitted IR
(`clang -O2 -Xclang -disable-llvm-passes -S -emit-llvm` or the equivalent
pipeline entry). Later passes and
LTO may fold, clone or rename functions, at which point name resolution is no
longer meaningful — the attributes produced here are the durable form.

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>' \
  -S build/demo.ll -o build/demo.protected.ll
```

For levels 2/3 add the control-flow pass after the decoys:

```
aegis-policy<policy=...>,aegis-decoys,aegis-cff,default<O2>,aegis-verify
```

`aegis-cff` reads the same attributes and refuses to run without the decoy
guard it builds on. See [`controlflow.md`](controlflow.md).

Before a transform pipeline, `aegis-lint` can be run directly after policy
resolution. It is read-only and applies the same eligibility rules:

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=policy.json>,aegis-lint' \
  -disable-output frontend.ll
```

The report names every selected function and any construct that would make a
level-2/3 build fail closed.

## Selection report

Written to stderr on every run:

```
[aegis-policy] policy="examples/aegis-policy.json"
[aegis-policy] schema=1 profile="dev"
[aegis-policy] select _Z15transform_valuei (transform_value(int)) level=1 reason="demo: protect transform_value"
[aegis-policy] summary: matched=1 declaration-only=0 missing=0
```

Feed this report (plus the LLVM/plugin versions) into build artifacts; it is
the auditable answer to "what was actually selected and why".

## Error cases

All validation problems are reported together in one run:

- unreadable file / invalid JSON / root not an object;
- missing `schema_version`, unsupported version;
- missing or unknown `profile`;
- `functions` not an array; entry not an object; missing or empty `name`;
  missing `level`; `level` outside `[0, 3]`;
- duplicate entries for the same name;
- `limits` fields negative or not integers.

Resolution failures fail the build: `not found`, `declaration-only`, and
ambiguous demangled matches.
