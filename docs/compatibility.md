# Compatibility matrix

Status: one supported environment. A second environment is admitted only
after the first release is stable — multiple half-tested matrices are worse
than one tested one.

## Supported today

| Axis | Supported | Notes |
|---|---|---|
| OS / arch | Linux x86-64 (Ubuntu 24.04 in `docker/dev.Dockerfile`) | CI and all published numbers run here |
| LLVM / Clang | 23.x (pinned 23.1.5) | LLVM API breakage is the main risk; the plugin is source-incompatible with older majors by construction |
| C++ standard | C++17 for the plugin and fixtures | `std::string` ABI must match the LLVM build (`_GLIBCXX_USE_CXX11_ABI=1`) |
| CMake | >= 3.20 | |
| Python (bench) | 3.10+ | stdlib only; no third-party packages |
| Sanitizers | ASan+UBSan on the *fixture*, in the `baseline-asan` profile | plugin not instrumented |

Exact versions are in [`dev-environment.md`](dev-environment.md).

## Explicitly unsupported

These are rejected, not silently mishandled:

| Case | Behaviour |
|---|---|
| LLVM other than 23.x | configure fails at `find_package(LLVM)` or the build breaks on API changes — do not report these as bugs |
| Policy level outside `0..3` | `aegis-policy` **fails the build**; levels 1–3 are implemented |
| Selected function with `optnone` / `naked` / EH personality / `musttail` | **fails the build** with the reason per function, rather than skipping (levels 1–3) |
| Level-3 selection of `indirectbr`, `callbr`, an EH terminator, or a coroutine | `aegis-cff` **fails the build** naming the function and construct; the flattening rewrite cannot preserve those safely |
| `aegis-cff` without `aegis-decoys` | **fails the build**: the live split is built on the decoy guard branch |
| Aegis passes placed after `default<O2>` | `aegis-verify` fails the build (guarded copies were inlined away); the error names the fix |
| Windows / macOS builds of the plugin | unbuilt and untested; the bench harness happens to run on Windows for development but is not supported there |
| LTO | untested. Frontend-IR ordering makes it plausible, but no result exists, so it is not claimed |

## Why fail rather than skip

A silently skipped function is a binary that the policy file claims is
protected. That is the one failure mode this project cannot tolerate: it turns
a build into a false statement. Every unsupported selection therefore stops
the build with the function name and the reason, so the operator chooses
between lowering the policy, changing the build, or waiting for the feature.

## Adding an environment

1. Add a job that runs the full CTest suite plus the two smoke tests.
2. Publish a differential report from that environment; sizes and timings from
   a different toolchain are not comparable, so keep them separate.
3. Update this file and CI together; an environment listed here without a
   green job is a documentation bug.
