# Aegis protection engineering scorecard

- Baseline profile: `baseline`
- Overall gate: **PASS**

This report is deterministic. It does not invoke a model, tool-using Agent, or external service. A passing scorecard means the configured profiles stayed inside their correctness and cost budgets; it is not an attacker-effectiveness claim.

| profile | role | gate | `.text` delta | p95 delta | build delta | mismatches | sanitizer | result |
|---|---|---|---:|---:|---:|---:|---:|---|
| baseline | observation | no | +0.00% | +0.00% | +0.00% | 0 | 0 | n/a |
| aegis-standard | default | yes | +20.54% | +21.79% | -3.83% | 0 | 0 | PASS |
| aegis-research | research | no | +12.88% | +29.95% | -13.25% | 0 | 0 | PASS |
| aegis-flattened | research | no | +58.64% | +923.79% | -24.51% | 0 | 0 | FAIL |

## Gate details

### `aegis-standard`

- PASS: `cases` = 75 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 20.535830407075043 (requires <= 30.00% (.text))
- PASS: `runtime_delta_pct` = 21.788946782018193 (requires <= 25.00% (runtime p95))
- PASS: `build_delta_pct` = -3.825018681306601 (requires <= 30.00% (build time))

### `aegis-research`

- PASS: `cases` = 75 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 12.875536480686694 (requires <= 50.00% (.text))
- PASS: `runtime_delta_pct` = 29.950666170299446 (requires <= 30.00% (runtime p95))
- PASS: `build_delta_pct` = -13.247697199949013 (requires <= 45.00% (build time))

### `aegis-flattened`

- PASS: `cases` = 75 (requires > 0)
- PASS: `output_mismatches` = 0 (requires == 0)
- PASS: `sanitizer_or_property_errors` = 0 (requires == 0)
- PASS: `build_samples` = {'profile': 3, 'baseline': 3} (requires >= 3 for both arms)
- PASS: `text_delta_pct` = 58.64221615294577 (requires <= 80.00% (.text))
- FAIL: `runtime_delta_pct` = 923.7912418763045 (requires <= 100.00% (runtime p95))
- PASS: `build_delta_pct` = -24.50601028739905 (requires <= 60.00% (build time))
