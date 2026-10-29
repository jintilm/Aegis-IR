# CI gates

One workflow (`.github/workflows/ci.yml`) runs on every push to `main`, every
pull request, and on demand. It has read-only repository permissions, a
30-minute timeout, and cancels superseded PR runs.

## What a PR must pass

| Step | Fails when | Why it exists |
|---|---|---|
| Build | the plugin does not compile against pinned LLVM | first gate |
| Smoke test (audit) | the pass plugin stops loading / reporting | catches registration and loading regressions |
| Smoke test (decoy pipeline) | policy → decoys → `default<O2>` → verify does not produce a guarded, verified module | proves the transform still survives the optimizer |
| Smoke test (control-flow pipeline) | a level-3 policy → decoys → cff → `default<O2>` → verify does not keep the volatile dispatch state | proves flattening survives the optimizer outside CTest |
| Smoke test (gate fails closed) | skipping `aegis-decoys` does **not** break the build | the verifier's entire value is failing loudly; a gate that silently passes is worse than none |
| Bench task integrity | a task file changed without re-recording `content_hash` | a result must name the task it actually ran |
| Python sanity | harness sources are not importable (`compileall`) | cheap syntax gate |
| Format check | `clang-format --dry-run -Werror` reports a diff | review noise reduction |
| Repository hygiene | private material tracked, a file > 1 MiB, or a credential-shaped string | a benchmark repo that leaks hidden answers or keys is worse than one that fails |
| Tests | any CTest suite fails (`aegis-policy`, `aegis-decoys`, `aegis-controlflow`, `differential`, `aegis-bench`) | behavioural gate |

Artifacts uploaded on every outcome: `differential-report.json` and the CTest
log, retained 30 days. A failing run therefore always has numbers attached.

## Merge rules

- CI must be green. No administrator overrides for behavioural gates; if a
  gate is wrong, fix the gate in the same PR that needs it.
- A new transform ships with: differential coverage, a stated limitation, and
  a doc section describing what it does *not* do.
- Any change to the default profile (`aegis-standard`) attaches before/after
  numbers from `build/differential-report.json`: `.text`/`.data` growth and
  p95 wall time.
- Research features are off by default and require an explicit policy level.
  A level a release does not implement must **fail the build**, never be
  ignored. Levels 1–3 are implemented; the shipped `aegis-standard` profile
  stays at level 1.
- No large binaries, private grading answers, credentials, or personal data.
- Commit messages use `feat:` / `fix:` / `test:` / `docs:` / `build:` /
  `chore:`.

## Not yet in CI

Stated so nobody assumes coverage that does not exist:

- **Sanitizers on the plugin itself.** The differential matrix runs the
  fixture under ASan/UBSan (`baseline-asan` profile), which covers the
  *transformed program*; the plugin's own memory safety is only exercised by
  running it, not by an instrumented build.
- **Static analysis** (`clang-tidy`) — planned, blocked on deciding whether
  LLVM headers make the false-positive rate worth it.
- **MAC/Windows jobs.** Single-environment policy until the first release
  (see `compatibility.md`).
- **Benchmark runs against real models.** Offline by design; those runs happen
  outside CI and publish into the claims ledger.
