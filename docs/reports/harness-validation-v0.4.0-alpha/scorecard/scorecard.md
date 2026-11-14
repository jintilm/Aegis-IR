# Aegis protection engineering scorecard

- Baseline profile: `release-opt`
- Overall gate: **PASS**

This report is deterministic. It does not invoke a model, tool-using Agent, or external service. A passing scorecard means the configured profiles stayed inside their correctness and cost budgets; it is not an attacker-effectiveness claim.

| profile | role | gate | `.text` delta | p95 delta | build delta | mismatches | sanitizer | result |
|---|---|---|---:|---:|---:|---:|---:|---|
| baseline | observation | no | +0.00% | +0.00% | -2.07% | 0 | 0 | n/a |
| release | observation | no | +0.00% | +9.19% | -1.93% | 0 | 0 | n/a |
| release-opt | observation | no | +0.00% | +12.26% | +0.00% | 0 | 0 | n/a |
| aegis-standard | default | yes | +22.08% | +8.86% | +0.77% | 0 | 0 | PASS |
| aegis-research | research | no | +12.92% | +4.31% | +8.40% | 0 | 0 | PASS |
| aegis-flattened | research | no | +32.23% | +10.25% | +6.08% | 0 | 0 | PASS |
| aegis-debug | observation | no | +173.18% | +10.98% | -8.41% | 0 | 0 | n/a |
| baseline-asan | observation | no | +28383.68% | +524.93% | +22.30% | 0 | 0 | n/a |

## Gate details

### `aegis-standard`

- PASS: `cases` = 235 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 22.078439179773042 (requires <= 25.00% (.text))
- PASS: `runtime_delta_pct` = 8.85617107573915 (requires <= 25.00% (runtime p95))
- PASS: `build_delta_pct` = 0.76876974491629 (requires <= 25.00% (build time))

### `aegis-research`

- PASS: `cases` = 235 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 12.920565399163847 (requires <= 25.00% (.text))
- PASS: `runtime_delta_pct` = 4.309798251974084 (requires <= 8.00% (runtime p95))
- PASS: `build_delta_pct` = 8.398904391394465 (requires <= 30.00% (build time))

### `aegis-flattened`

- PASS: `cases` = 235 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 32.23173402349194 (requires <= 40.00% (.text))
- PASS: `runtime_delta_pct` = 10.253648808821714 (requires <= 35.00% (runtime p95))
- PASS: `build_delta_pct` = 6.079183803438442 (requires <= 35.00% (build time))
