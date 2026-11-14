# External workload smoke tests

The release gate is self-contained and network-free. External code is useful
as an optional compatibility check, not as another release dependency.

## Pinned tiny-AES-c smoke

[`tests/external/run_tiny_aes.py`](../tests/external/run_tiny_aes.py) fetches
`kokke/tiny-AES-c` at a fixed commit, verifies the checkout, generates a
temporary AES-128 ECB fixture and runs it through the normal differential
runner:

```bash
python3 tests/external/run_tiny_aes.py \
  --plugin build/lib/AegisPass.so \
  --report build/tiny-aes-external-report.json \
  --markdown build/tiny-aes-external-report.md
```

Pin data:

| Field | Value |
|---|---|
| Repository | `https://github.com/kokke/tiny-AES-c.git` |
| Commit | `23856752fbd139da0b8ca6e471a13d5bcc99a08d` |
| License | Unlicense |
| Upstream files | `aes.c`, `aes.h` |
| Selected wrapper | `aegis_external_aes_block` |
| Profiles | baseline, standard, research, flattened |
| Corpus | 75 deterministic cases |

The script copies the external files into a temporary fixture only. The
upstream source is never vendored into this repository, and CI does not run
this path because CI intentionally has no network dependency.

The smoke checks that:

- the external C code compiles through the frontend-IR pipeline;
- selected C functions can be protected at levels 1-3;
- protected outputs match baseline across fixed, boundary and fuzz inputs;
- no sanitizer or property failures occur;
- code-size, p95 and three-build medians are recorded.

This is a compatibility and semantic-preservation check. It is not a
production benchmark, does not generalize to arbitrary external code and does
not establish attack resistance.

## Adding another external workload

Use an immutable commit and a license that permits local use and publication
of results. Do not copy third-party source into the repository. Generate a
temporary fixture with:

- `algorithm_lib.cpp`;
- `driver.cpp`;
- `profiles.json`;
- one policy per protected profile.

Then invoke `tests/differential/run.py` with `--fixture-dir` and `--profiles`.
Record the upstream URL, commit, license, source-file hashes and benchmark
commit in the resulting report. Keep the workload outside CTest unless it can
be vendored under a compatible license and made fully deterministic offline.
