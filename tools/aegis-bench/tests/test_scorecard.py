"""Tests for deterministic protection engineering budgets."""

from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent
sys.path.insert(0, str(TOOL_ROOT))

from aegis_bench.scorecard import (  # noqa: E402
    ScorecardError, evaluate_scorecard, load_budgets, write_scorecard)


def _differential(
        *, text: int = 1200, p95: float = 10.2, build: float = 110.0,
        mismatches: int = 0, sanitizer: int = 0) -> dict:
    base_samples = [99.0, 100.0, 101.0]
    build_samples = [build - 10.0, build, build + 10.0]
    return {
        "runtime_baseline_profile": "release-opt",
        "profiles": {
            "release-opt": {
                "sections": {"text": 1000},
                "p95_ms": 10.0,
                "build_samples_ms": base_samples,
                "build_median_ms": 100.0,
                "build_ms": 100.0,
                "cases": 235,
                "mismatches": 0,
                "sanitizer_or_property_errors": 0,
            },
            "aegis-standard": {
                "sections": {"text": text},
                "p95_ms": p95,
                "relative_p95_delta_pct": (p95 / 10.0 - 1.0) * 100.0,
                "build_samples_ms": build_samples,
                "build_median_ms": build,
                "build_ms": build,
                "cases": 235,
                "mismatches": mismatches,
                "sanitizer_or_property_errors": sanitizer,
            },
        },
    }


def _budgets(tmp: str) -> dict:
    path = Path(tmp) / "budgets.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "baseline_profile": "release-opt",
        "min_build_samples": 3,
        "profiles": {
            "aegis-standard": {
                "role": "default",
                "gate": True,
                "max_text_delta_pct": 25.0,
                "max_p95_delta_pct": 3.0,
                "max_build_delta_pct": 25.0,
            },
        },
    }), encoding="utf-8")
    return load_budgets(path)


class ScorecardTests(unittest.TestCase):
    def test_runtime_baseline_must_be_explicit_and_match_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            budgets = _budgets(tmp)
            for baseline in (None, "baseline"):
                differential = _differential()
                differential["runtime_baseline_profile"] = baseline
                with self.subTest(baseline=baseline), self.assertRaisesRegex(
                        ScorecardError, "runtime baseline"):
                    evaluate_scorecard(differential, budgets)

    def test_missing_paired_metric_cannot_fall_back_to_unpaired_p95(self):
        differential = _differential()
        del differential["profiles"]["aegis-standard"]["relative_p95_delta_pct"]
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scorecard(differential, _budgets(tmp))
        self.assertFalse(result["passed"])

    def test_different_correctness_and_runtime_baselines_use_paired_samples(self):
        runner_path = TOOL_ROOT.parents[1] / "tests/differential/run.py"
        spec = importlib.util.spec_from_file_location("differential_runner", runner_path)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        timings = {
            "baseline": [[8.0] * 3, [16.0] * 3],
            "release-opt": [[10.0] * 3, [20.0] * 3],
            "aegis-standard": [[12.0] * 3, [24.0] * 3],
        }
        metrics = runner.runtime_metrics(timings, "release-opt", 3)
        self.assertEqual(metrics["release-opt"]["relative_p95_delta_pct"], 0.0)
        self.assertAlmostEqual(metrics["aegis-standard"]["relative_p95_delta_pct"], 20.0)
        differential = _differential()
        for name in differential["profiles"]:
            differential["profiles"][name].update(metrics[name])
        with tempfile.TemporaryDirectory() as tmp:
            budgets = _budgets(tmp)
            budgets["profiles"]["aegis-standard"]["max_p95_delta_pct"] = 25
            self.assertTrue(evaluate_scorecard(differential, budgets)["passed"])
        timings["aegis-standard"][0].pop()
        incomplete = runner.runtime_metrics(timings, "release-opt", 3)
        self.assertIsNone(incomplete["aegis-standard"]["relative_p95_delta_pct"])
        self.assertEqual(runner.percentile(list(range(1, 11)), 95), 10)

    def test_within_budget_passes_and_writes_machine_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scorecard(_differential(), _budgets(tmp))
            paths = write_scorecard(result, Path(tmp) / "out")
            raw = json.loads(paths["json"].read_text(encoding="utf-8"))
            markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertTrue(result["passed"])
        self.assertTrue(raw["passed"])
        self.assertIn("Overall gate: **PASS**", markdown)
        self.assertIn("`aegis-standard`", markdown)

    def test_cost_or_correctness_regression_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            budgets = _budgets(tmp)
            result = evaluate_scorecard(
                _differential(text=1300, p95=12.0, mismatches=1),
                budgets)
        self.assertFalse(result["passed"])
        checks = {
            check["name"]: check["ok"]
            for check in result["profiles"]["aegis-standard"]["checks"]
        }
        self.assertFalse(checks["output_mismatches"])
        self.assertFalse(checks["text_delta_pct"])
        self.assertFalse(checks["runtime_delta_pct"])

    def test_missing_timed_metric_fails_a_configured_budget(self):
        differential = _differential()
        del differential["profiles"]["aegis-standard"]["build_median_ms"]
        del differential["profiles"]["aegis-standard"]["build_ms"]
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scorecard(differential, _budgets(tmp))
        checks = {
            check["name"]: check["ok"]
            for check in result["profiles"]["aegis-standard"]["checks"]
        }
        self.assertFalse(checks["build_delta_pct"])
        self.assertFalse(result["passed"])

    def test_build_median_is_preferred_over_legacy_scalar(self):
        differential = _differential()
        differential["profiles"]["aegis-standard"]["build_median_ms"] = 105.0
        differential["profiles"]["aegis-standard"]["build_ms"] = 999.0
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scorecard(differential, _budgets(tmp))
        profile = result["profiles"]["aegis-standard"]
        self.assertEqual(profile["build_ms"], 105.0)
        self.assertAlmostEqual(profile["build_delta_pct"], 5.0)
        self.assertTrue(result["passed"])

    def test_too_few_build_samples_fails_the_gate(self):
        differential = _differential()
        differential["profiles"]["aegis-standard"]["build_samples_ms"] = [110.0]
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scorecard(differential, _budgets(tmp))
        checks = {
            check["name"]: check["ok"]
            for check in result["profiles"]["aegis-standard"]["checks"]
        }
        self.assertFalse(checks["build_samples"])
        self.assertFalse(result["passed"])

    def test_missing_gated_profile_fails(self):
        differential = _differential()
        del differential["profiles"]["aegis-standard"]
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate_scorecard(differential, _budgets(tmp))
        self.assertFalse(result["passed"])
        self.assertFalse(
            result["profiles"]["aegis-standard"]["checks"][0]["ok"])

    def test_invalid_budget_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budgets.json"
            path.write_text('{"schema_version": 99}', encoding="utf-8")
            with self.assertRaises(ScorecardError):
                load_budgets(path)


if __name__ == "__main__":
    unittest.main()
