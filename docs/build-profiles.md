# Build profiles and differential testing

Status: implemented for fixtures; transforms land into these profiles as they
are admitted.

## The six profiles

Defined in `tests/differential/profiles.json`:

| Profile | Flags | Protection | Strip | Purpose |
|---|---|---|---|---|
| `baseline` | `-O2` | none | no | reference behaviour; every comparison target |
| `release` | `-O2` | none | yes | fair "what the world sees" baseline |
| `aegis-standard` | `-O2` | policy `standard.json` (Tier 1) | yes | shipped protection |
| `aegis-research` | `-O2` | policy `research.json` (Tiers 2–3) | yes | research features; placeholder until transforms exist |
| `aegis-debug` | `-O0 -g` | none | no | official debugging artifact for protected programs |
| `baseline-asan` | `-O1 -fsanitize=address,undefined` | none | no | memory/UB safety net for the corpus |

`aegis-debug` is the supported answer to "protection broke production
debugging": rebuild the same commit with it, reproduce, fix. `aegis-research`
currently runs the same empty transform pipeline as `aegis-standard` with a
different policy — it exists so experimental transforms have a wired target
that is off by default.

## Fixture

The differential fixture mirrors the primary target scenario: an **offline
C++ algorithm library** (`tests/differential/fixtures/algorithm_lib.cpp`,
FNV-1a hash, Adler-32-style checksum, token predicate) built as its own
translation unit, plus an unprotected driver. Only the library TU passes
through the protection pipeline.

## What the runner does

`tests/differential/run.py`:

1. **Builds every profile** — compiles the library to IR, runs
   `aegis-policy<policy=...>` for protected profiles (a policy failure is a
   test failure), compiles the protected IR, links with the driver.
2. **Generates the corpus deterministically** — fixed cases, boundary
   lengths (0–1025 around 8/17/64/256/1024), and `--fuzz-cases` seeded random
   byte strings (default 200, seed 1234).
3. **Executes every corpus case through every profile**, comparing stdout and
   exit code against `baseline`.
4. **Fails on**: output/exit mismatches, timeouts, `PROPERTY FAIL` lines from
   the driver's contract assertions, and any ASan/UBSan report in stderr.
5. **Records the size/time baseline** — binary bytes, total corpus time per
   profile — into `build/differential-report.json`. These numbers are the
   denominator for the cost ledger when transforms arrive.

Run it directly:

```bash
python3 tests/differential/run.py --plugin build/lib/AegisPass.so
ctest --test-dir build --output-on-failure      # both suites
```

## Failure policy (from the plan)

When a profile breaks:

1. Save the failing input as a regression corpus entry.
2. A transform that fails differential testing never enters the default
   profile with the failure present.
3. Produce a minimal repro: input, build profile, flags, tool versions.
4. After a fix, the full suite is re-run — never only the failed case.

## Known limitations

- The corpus is synthetic; size/time baselines from it do not extrapolate to
  real large software.
- stderr is not compared across profiles (diagnostic noise); only property and
  sanitizer signatures are scanned.
- `aegis-research` is a placeholder target until research transforms exist.