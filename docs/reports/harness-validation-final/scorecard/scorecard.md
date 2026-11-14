# Aegis protection engineering scorecard

- Baseline profile: `release-opt`
- Overall gate: **PASS**

This report is deterministic. It does not invoke a model, tool-using Agent, or external service. A passing scorecard means the configured profiles stayed inside their correctness and cost budgets; it is not an attacker-effectiveness claim.

| profile | role | gate | `.text` delta | p95 delta | build delta | mismatches | sanitizer | result |
|---|---|---|---:|---:|---:|---:|---:|---|
| baseline | observation | no | +0.00% | +0.00% | +0.67% | 0 | 0 | n/a |
| release | observation | no | +0.00% | +5.52% | +10.20% | 0 | 0 | n/a |
| release-opt | observation | no | +0.00% | +3.63% | +0.00% | 0 | 0 | n/a |
| aegis-standard | default | yes | +22.08% | +6.26% | +0.11% | 0 | 0 | PASS |
| aegis-research | research | no | +12.92% | +6.35% | +14.05% | 0 | 0 | PASS |
| aegis-flattened | research | no | +32.23% | +7.72% | +17.12% | 0 | 0 | PASS |
| aegis-debug | observation | no | +173.18% | +5.54% | +4.34% | 0 | 0 | n/a |
| baseline-asan | observation | no | +28383.68% | +505.36% | +19.98% | 0 | 0 | n/a |

## Gate details

### `aegis-standard`

- PASS: `cases` = 235 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 22.078439179773042 (requires <= 25.00% (.text))
- PASS: `runtime_delta_pct` = 6.262558399629903 (requires <= 25.00% (runtime p95))
- PASS: `build_delta_pct` = 0.1081555331940128 (requires <= 25.00% (build time))

### `aegis-research`

- PASS: `cases` = 235 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 12.920565399163847 (requires <= 25.00% (.text))
- PASS: `runtime_delta_pct` = 6.352188785028656 (requires <= 8.00% (runtime p95))
- PASS: `build_delta_pct` = 14.048803478706324 (requires <= 30.00% (build time))

### `aegis-flattened`

- PASS: `cases` = 235 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 32.23173402349194 (requires <= 40.00% (.text))
- PASS: `runtime_delta_pct` = 7.7247604368822165 (requires <= 35.00% (runtime p95))
- PASS: `build_delta_pct` = 17.123647932827897 (requires <= 35.00% (build time))
