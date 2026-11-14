# Aegis protection engineering scorecard

- Baseline profile: `baseline`
- Overall gate: **PASS**

This report is deterministic. It does not invoke a model, tool-using Agent, or external service. A passing scorecard means the configured profiles stayed inside their correctness and cost budgets; it is not an attacker-effectiveness claim.

| profile | role | gate | `.text` delta | p95 delta | build delta | mismatches | sanitizer | result |
|---|---|---|---:|---:|---:|---:|---:|---|
| baseline | observation | no | +0.00% | +0.00% | +0.00% | 0 | 0 | n/a |
| aegis-standard | default | yes | +20.54% | +18.39% | +9.68% | 0 | 0 | PASS |
| aegis-research | research | no | +12.88% | +22.38% | +3.18% | 0 | 0 | PASS |
| aegis-flattened | research | no | +58.64% | +925.64% | +8.89% | 0 | 0 | FAIL |

## Gate details

### `aegis-standard`

- PASS: `cases` = 75 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 20.535830407075043 (requires <= 30.00% (.text))
- PASS: `runtime_delta_pct` = 18.392409048642723 (requires <= 25.00% (runtime p95))
- PASS: `build_delta_pct` = 9.67697289108603 (requires <= 30.00% (build time))

### `aegis-research`

- PASS: `cases` = 75 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 12.875536480686694 (requires <= 50.00% (.text))
- PASS: `runtime_delta_pct` = 22.3788305627294 (requires <= 30.00% (runtime p95))
- PASS: `build_delta_pct` = 3.1843904815931787 (requires <= 45.00% (build time))

### `aegis-flattened`

- PASS: `cases` = 75 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 58.64221615294577 (requires <= 80.00% (.text))
- FAIL: `runtime_delta_pct` = 925.6363820439112 (requires <= 100.00% (runtime p95))
- PASS: `build_delta_pct` = 8.894333903563233 (requires <= 60.00% (build time))
