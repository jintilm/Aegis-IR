# Build profiles and differential testing

Status: implemented for fixtures; transforms land into these profiles as they
are admitted.

## The eight profiles

Defined in `tests/differential/profiles.json`:

| Profile | Flags | Protection | Strip | Purpose |
|---|---|---|---|---|
| `baseline` | `-O2` | none | no | reference behaviour; every comparison target |
| `release` | `-O2` | none | yes | fair "what the world sees" baseline |
| `release-opt` | `-O2` | `default<O2>` via `opt` | yes | isolates driver overhead / IR round-trip from protection |
| `aegis-standard` | `-O2` | policy level 1, decoys, verify | yes | shipped protection |
| `aegis-research` | `-O2` | policy level 2, decoys, cff, verify | yes | live split + bogus edges |
| `aegis-flattened` | `-O2` | policy level 3, decoys, cff, verify | yes | control-flow flattening |
| `aegis-debug` | `-O0 -g` | none | no | official debugging artifact for protected programs |
| `baseline-asan` | `-O1 -fsanitize=address,undefined` | none | no | memory/UB safety net for the corpus |

`release-opt` exists because protected profiles have their IR round-tripped
through `opt`; without it, a difference between `release` and
`aegis-standard` could be attributed to protection when it is really pipeline
overhead.

Protected profiles use the full pipeline
`aegis-policy<policy=...>,aegis-decoys,aegis-cff,default<O2>,aegis-verify`.
The level-1 profile's `aegis-cff` invocation is a no-op; levels 2/3 rely on it.

`aegis-debug` is the supported answer to "protection broke production
debugging": rebuild the same commit with it, reproduce, fix. Research levels
are off by default: `aegis-standard` stays at level 1, and levels 2/3 require
an explicit policy change. The research profiles use different seeds
(777/778), so their sizes are each comparable to the shared baseline, not to
each other as a ladder.

## Fixtures

The differential fixture mirrors the primary target scenario: an **offline
C++ algorithm library** (`tests/differential/fixtures/algorithm_lib.cpp`,
FNV-1a hash, Adler-32-style checksum, token predicate) built as its own
translation unit, plus an unprotected driver. Only the library TU passes
through the protection pipeline.

The representative suite
(`tests/differential/suites/representative/`) uses the same runner and a
larger parser/fold/round/digest workload that performs at least 1 MiB of work
per invocation. It is intended to expose stable protected hot-path overhead;
it is not a production benchmark and does not generalize to arbitrary code.

## What the runner does

`tests/differential/run.py`:

1. **Builds every profile** — compiles the library to IR, runs the profile
   pipeline through `opt` (a failure is a test failure), compiles the
   protected IR, links with the driver. Profiles with a `pipeline` entry
   compile to *frontend* IR (`-Xclang -disable-llvm-passes`) so the transform
   sees the module before inlining; see [`decoys.md`](decoys.md) and
   [`controlflow.md`](controlflow.md).
2. **Generates the corpus deterministically** — fixed cases, boundary
   lengths (0–1025 around 8/17/64/256/1024), and `--fuzz-cases` seeded random
   byte strings (default 200, seed 1234).
3. **Executes every corpus case through every profile**, comparing stdout and
   exit code against `baseline`.
4. **Fails on**: output/exit mismatches, timeouts, `PROPERTY FAIL` lines from
   the driver's contract assertions, and any ASan/UBSan report in stderr.
5. **Records the size/time baseline** — binary bytes, `.text`/`.data` section
   totals, three independent clean-build samples and their median, plus
   interleaved per-profile p95 wall time. Section totals matter because file
   size is page-quantised: small transforms change `.text` without changing
   the file size. These numbers are the denominator for the cost ledger.

Run it directly:

```bash
python3 tests/differential/run.py --plugin build/lib/AegisPass.so
python3 tests/differential/run.py --plugin build/lib/AegisPass.so \
  --fixture-dir tests/differential/suites/representative \
  --profiles tests/differential/suites/representative/profiles.json \
  --fuzz-cases 40 \
  --report build/representative-differential-report.json
ctest --test-dir build --output-on-failure      # all suites
```

## Failure policy (from the plan)

When a profile breaks:

1. Save the failing input as a regression corpus entry.
2. A transform that fails differential testing never enters the default
   profile with the failure present.
3. Produce a minimal repro: input, build profile, flags, tool versions.
4. After a fix, the full suite is re-run — never only the failed case.

## Known limitations

- Both corpora are synthetic; size/time baselines do not extrapolate to real
  large software.
- stderr is not compared across profiles (diagnostic noise); only property and
  sanitizer signatures are scanned.
- `aegis-standard` remains level 1 by default. Levels 2/3 are research
  profiles; flattening is not recommended for hot paths (volatile state access
  per block).
- The small fixture remains process-startup dominated. The representative
  workload performs at least 1 MiB of work per run, but it is still an
  engineering regression workload, not a production-performance claim.
