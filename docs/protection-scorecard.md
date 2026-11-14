# Protection engineering scorecard

The default Aegis release path is deterministic. It does not call an LLM,
start an attack campaign, or spend provider tokens. The scorecard evaluates
two complementary differential workloads as explicit engineering gates:

- a small fixture that is a fast semantic and transform regression tripwire;
- a larger representative algorithm workload designed to reduce
  process-startup and scheduling noise.

Both are engineering workloads, not production benchmarks. The gates cover:

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
[`experiments/protection-budgets.json`](../experiments/protection-budgets.json)
for the fixture and
[`experiments/protection-budgets-representative.json`](../experiments/protection-budgets-representative.json)
for the representative suite. The default profile is `aegis-standard`:

| Budget | Fixture | Representative |
|---|---:|---:|
| Output mismatches | 0 | 0 |
| Sanitizer/property errors | 0 | 0 |
| `.text` growth | <= 25% | <= 30% |
| paired relative p95 growth | <= 25% | <= 25% |
| Build-time median growth | <= 25% | <= 30% |

Build time is the median of three independent clean builds in each arm. A
configured profile with fewer than three samples fails the gate rather than
being accepted on a noisy scalar.

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

python3 ../../tests/differential/run.py \
  --plugin ../../build/lib/AegisPass.so \
  --fixture-dir ../../tests/differential/suites/representative \
  --profiles ../../tests/differential/suites/representative/profiles.json \
  --fuzz-cases 40 \
  --report ../../build/representative-differential-report.json

python3 -m aegis_bench scorecard \
  --differential ../../build/representative-differential-report.json \
  --budgets ../../experiments/protection-budgets-representative.json \
  --out ../../build/scorecard-representative
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

`scripts/release-report.sh` requires all eight CTest targets, both differential
reports, and both scorecards to pass before writing the release report. This
replaces repeated AI attack matrices as the routine release gate.

The scorecards are CTest targets: `protection-scorecard` depends on
`differential`, and `protection-scorecard-representative` depends on
`differential-representative`.

## Limitations

- The fixture is a small regression tripwire. The representative suite adds
  sustained work but is still synthetic and self-authored, not a production
  benchmark.
- The small fixture's paired p95 is process-startup dominated, so its runtime
  limit is calibrated as a gross-regression tripwire rather than a tight
  performance target. The representative suite is the stronger runtime check.
- Build time uses a median of three independent clean builds. It is still a
  local tripwire, not a build-throughput benchmark.
- Paired p95 is stable enough for the calibrated representative release gate,
  but it does not establish overhead on arbitrary production code.
- Scorecard success says the default profile stayed within engineering
  budgets. It says nothing about how hard an attacker finds the binary.
- Attacker cost, model drift and white-box filtering remain research
  questions to run selectively, not continuously.
