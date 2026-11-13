# Protection engineering scorecard

The default Aegis release path is deterministic. It does not call an LLM,
start an attack campaign, or spend provider tokens. The scorecard turns the
differential fixture into explicit engineering gates for the protection
profiles:

- semantic correctness against the baseline corpus;
- output mismatches and sanitizer/property failures;
- `.text` growth;
- paired relative p95 runtime regression;
- build-time regression.

Model campaigns remain useful when there is a specific cost question, but they
are optional external evidence. They are no longer the normal route for
developing or validating the protection plugin.

## Baseline and budgets

`release-opt` is the baseline because it goes through the same `opt` round trip
as protected profiles. Comparing against plain `release` would charge the IR
pipeline itself to the protection transform.

Budgets live in
[`experiments/protection-budgets.json`](../experiments/protection-budgets.json).
The default profile is `aegis-standard`:

| Budget | Default |
|---|---:|
| Output mismatches | 0 |
| Sanitizer/property errors | 0 |
| `.text` growth | <= 25% |
| paired relative p95 growth | <= 3% |
| Build-time growth | <= 25% |

Level 2/3 profiles are scored as research observations. They are reported, but
their budgets do not block a release. This matches the product boundary:
default protection must remain cheap and predictable; expensive flattening is
opt-in research.

## Command

Run the differential matrix, then evaluate the scorecard:

```bash
python3 tests/differential/run.py \
  --plugin build/lib/AegisPass.so \
  --report build/differential-report.json

cd tools/aegis-bench
python3 -m aegis_bench scorecard \
  --differential ../../build/differential-report.json \
  --budgets ../../experiments/protection-budgets.json \
  --out ../../build/scorecard
```

Outputs:

- `scorecard.json` for automation;
- `scorecard.md` for human review.

The runtime metric is not a comparison of two independently collected p95
values. Each corpus case is executed in an interleaved round for every
profile, repeated three times. For each case, the scorecard compares the mean
protected latency with the mean baseline latency, then takes the p95 of those
per-case ratios. This reduces host drift and process-startup noise.

The command exits non-zero when a gated profile exceeds a budget or lacks a
required measurement.

## Release integration

`scripts/release-report.sh` runs the scorecard after CTest and requires it to
pass before writing the release report. This replaces repeated AI attack
matrices as the routine release gate.

The scorecard is also a CTest target, `protection-scorecard`, which depends on
the `differential` test and reads its generated report.

## Limitations

- The fixture is synthetic and small; these are regression budgets, not broad
  production performance claims.
- Build time is a single cold sample per profile and can be noisy. It is a
  tripwire, not a precise benchmark.
- Even paired p95 remains process-startup dominated on this corpus. A separate
  realistic workload is still required before making production-overhead
  claims.
- Scorecard success says the default profile stayed within engineering
  budgets. It says nothing about how hard an attacker finds the binary.
- Attacker cost, model drift and white-box filtering remain research
  questions to run selectively, not continuously.
