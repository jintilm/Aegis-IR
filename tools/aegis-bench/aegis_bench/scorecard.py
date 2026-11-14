"""Deterministic engineering scorecard for Aegis protection profiles.

This report deliberately does not call a model. It turns the differential
fixture into release gates for correctness, .text growth, p95 regression and
build-time regression. Model campaigns remain optional external evidence about
attacker cost; they are not part of the default release loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .report import atomic_write_text

SCORECARD_SCHEMA_VERSION = 1


class ScorecardError(Exception):
    """The scorecard input or budget configuration is malformed."""


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorecardError(f"{name} must be a number")
    return float(value)


def load_budgets(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScorecardError(f"cannot read budgets: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScorecardError(f"invalid budget JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ScorecardError("budget file must be an object")
    if raw.get("schema_version") != SCORECARD_SCHEMA_VERSION:
        raise ScorecardError(
            f"schema_version must be {SCORECARD_SCHEMA_VERSION}")
    baseline = raw.get("baseline_profile")
    if not isinstance(baseline, str) or not baseline:
        raise ScorecardError("baseline_profile must be a non-empty string")
    min_build_samples = raw.get("min_build_samples", 1)
    if (isinstance(min_build_samples, bool)
            or not isinstance(min_build_samples, int)
            or min_build_samples < 1):
        raise ScorecardError("min_build_samples must be a positive integer")
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ScorecardError("profiles must be a non-empty object")
    for profile, rule in profiles.items():
        if not isinstance(profile, str) or not profile:
            raise ScorecardError("profile names must be non-empty strings")
        if not isinstance(rule, dict):
            raise ScorecardError(f"{profile}: rule must be an object")
        if not isinstance(rule.get("gate", False), bool):
            raise ScorecardError(f"{profile}: gate must be boolean")
        for key in ("max_text_delta_pct", "max_p95_delta_pct",
                    "max_build_delta_pct"):
            if key in rule and rule[key] is not None:
                _number(rule[key], f"{profile}.{key}")
                if rule[key] < 0:
                    raise ScorecardError(
                        f"{profile}.{key} must be non-negative")
    return raw


def _delta_pct(value: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return (value - baseline) / baseline * 100.0


def _profile_metrics(
        name: str, entry: dict[str, Any],
        baseline: dict[str, Any]) -> dict[str, Any]:
    sections = entry.get("sections") or {}
    base_sections = baseline.get("sections") or {}
    text = sections.get("text")
    base_text = base_sections.get("text")
    p95 = entry.get("p95_ms")
    base_p95 = baseline.get("p95_ms")
    relative_p95 = entry.get("relative_p95_delta_pct")
    build_samples = entry.get("build_samples_ms")
    if not isinstance(build_samples, list):
        build_samples = []
    build_sample_count = len(build_samples)
    base_samples = baseline.get("build_samples_ms")
    if not isinstance(base_samples, list):
        base_samples = []
    base_sample_count = len(base_samples)
    build = entry.get("build_median_ms")
    if not isinstance(build, (int, float)):
        build = entry.get("build_ms")
    base_build = baseline.get("build_median_ms")
    if not isinstance(base_build, (int, float)):
        base_build = baseline.get("build_ms")
    return {
        "profile": name,
        "cases": int(entry.get("cases", 0)),
        "mismatches": int(entry.get("mismatches", 0)),
        "sanitizer_or_property_errors": int(
            entry.get("sanitizer_or_property_errors", 0)),
        "text_bytes": text,
        "text_delta_pct": (
            _delta_pct(float(text), float(base_text))
            if isinstance(text, (int, float))
            and isinstance(base_text, (int, float)) else None),
        "p95_ms": p95,
        "p95_delta_pct": (
            _delta_pct(float(p95), float(base_p95))
            if isinstance(p95, (int, float))
            and isinstance(base_p95, (int, float)) else None),
        "relative_p95_delta_pct": relative_p95,
        "runtime_delta_pct": (
            float(relative_p95)
            if isinstance(relative_p95, (int, float))
            else (
                _delta_pct(float(p95), float(base_p95))
                if isinstance(p95, (int, float))
                and isinstance(base_p95, (int, float)) else None)),
        "build_ms": build,
        "build_samples_ms": build_samples,
        "build_sample_count": build_sample_count,
        "baseline_build_sample_count": base_sample_count,
        "build_delta_pct": (
            _delta_pct(float(build), float(base_build))
            if isinstance(build, (int, float))
            and isinstance(base_build, (int, float)) else None),
    }


def evaluate_scorecard(
        differential: dict[str, Any],
        budgets: dict[str, Any]) -> dict[str, Any]:
    profiles = differential.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ScorecardError("differential report has no profiles")
    baseline_name = budgets["baseline_profile"]
    baseline = profiles.get(baseline_name)
    if not isinstance(baseline, dict):
        raise ScorecardError(
            f"baseline profile {baseline_name!r} is missing")

    report_profiles: dict[str, Any] = {}
    missing_gated = [
        name for name, rule in budgets["profiles"].items()
        if rule.get("gate", False) and name not in profiles
    ]
    gate_pass = not missing_gated
    for name in missing_gated:
        rule = budgets["profiles"][name]
        report_profiles[name] = {
            "profile": name,
            "cases": 0,
            "mismatches": 0,
            "sanitizer_or_property_errors": 0,
            "text_bytes": None,
            "text_delta_pct": None,
            "p95_ms": None,
            "p95_delta_pct": None,
            "relative_p95_delta_pct": None,
            "runtime_delta_pct": None,
            "build_ms": None,
            "build_samples_ms": [],
            "build_sample_count": 0,
            "baseline_build_sample_count": 0,
            "build_delta_pct": None,
            "role": rule.get("role", "gated"),
            "gate": True,
            "passed": False,
            "checks": [{
                "name": "profile_present",
                "ok": False,
                "actual": "missing",
                "requirement": "present in differential report",
            }],
        }
    for name, entry in profiles.items():
        if not isinstance(entry, dict):
            raise ScorecardError(f"{name}: differential profile must be an object")
        rule = budgets["profiles"].get(name)
        metrics = _profile_metrics(name, entry, baseline)
        checks: list[dict[str, Any]] = []
        if rule is not None:
            min_build_samples = int(budgets.get("min_build_samples", 1))
            errors_required = bool(
                rule.get("require_zero_mismatches", True))
            sanitizer_required = bool(
                rule.get("require_zero_sanitizer_or_property_errors", True))
            checks.append({
                "name": "cases",
                "ok": metrics["cases"] > 0,
                "actual": metrics["cases"],
                "requirement": "> 0",
            })
            if errors_required:
                checks.append({
                    "name": "output_mismatches",
                    "ok": metrics["mismatches"] == 0,
                    "actual": metrics["mismatches"],
                    "requirement": "== 0",
                })
            if sanitizer_required:
                checks.append({
                    "name": "sanitizer_or_property_errors",
                    "ok": metrics["sanitizer_or_property_errors"] == 0,
                    "actual": metrics["sanitizer_or_property_errors"],
                    "requirement": "== 0",
                })
            minimum_observed = min(
                metrics["build_sample_count"],
                metrics["baseline_build_sample_count"])
            checks.append({
                "name": "build_samples",
                "ok": minimum_observed >= min_build_samples,
                "actual": {
                    "profile": metrics["build_sample_count"],
                    "baseline": metrics["baseline_build_sample_count"],
                },
                "requirement": f">= {min_build_samples} for both arms",
            })
            for metric, limit_key, label in (
                    ("text_delta_pct", "max_text_delta_pct", ".text"),
                    ("runtime_delta_pct", "max_p95_delta_pct", "runtime p95"),
                    ("build_delta_pct", "max_build_delta_pct", "build time")):
                limit = rule.get(limit_key)
                if limit is None:
                    continue
                actual = metrics[metric]
                checks.append({
                    "name": metric,
                    "ok": (actual is not None
                           and float(actual) <= float(limit)),
                    "actual": actual,
                    "requirement": f"<= {float(limit):.2f}% ({label})",
                })
            passed = all(check["ok"] for check in checks)
            if rule.get("gate", False) and not passed:
                gate_pass = False
        else:
            passed = None
        report_profiles[name] = {
            **metrics,
            "role": (rule or {}).get("role", "observation"),
            "gate": bool((rule or {}).get("gate", False)),
            "passed": passed,
            "checks": checks,
        }

    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "baseline_profile": baseline_name,
        "passed": gate_pass,
        "profiles": report_profiles,
    }


def _fmt(value: Any, suffix: str = "") -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):+.2f}{suffix}"


def markdown_scorecard(result: dict[str, Any]) -> str:
    lines = [
        "# Aegis protection engineering scorecard",
        "",
        f"- Baseline profile: `{result['baseline_profile']}`",
        f"- Overall gate: **{'PASS' if result['passed'] else 'FAIL'}**",
        "",
        "This report is deterministic. It does not invoke a model, tool-using "
        "Agent, or external service. A passing scorecard means the configured "
        "profiles stayed inside their correctness and cost budgets; it is not "
        "an attacker-effectiveness claim.",
        "",
        "| profile | role | gate | `.text` delta | p95 delta | build delta | "
        "mismatches | sanitizer | result |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, profile in result["profiles"].items():
        status = ("n/a" if profile["passed"] is None
                  else "PASS" if profile["passed"] else "FAIL")
        lines.append(
            f"| {name} | {profile['role']} | "
            f"{'yes' if profile['gate'] else 'no'} | "
            f"{_fmt(profile['text_delta_pct'], '%')} | "
            f"{_fmt(profile['runtime_delta_pct'], '%')} | "
            f"{_fmt(profile['build_delta_pct'], '%')} | "
            f"{profile['mismatches']} | "
            f"{profile['sanitizer_or_property_errors']} | {status} |")
    lines += ["", "## Gate details", ""]
    for name, profile in result["profiles"].items():
        if not profile["checks"]:
            continue
        lines += [f"### `{name}`", ""]
        for check in profile["checks"]:
            status = "PASS" if check["ok"] else "FAIL"
            lines.append(
                f"- {status}: `{check['name']}` = {check['actual']} "
                f"(requires {check['requirement']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_scorecard(result: dict[str, Any], out_dir: str | Path
                    ) -> dict[str, Path]:
    out = Path(out_dir)
    paths = {
        "json": out / "scorecard.json",
        "markdown": out / "scorecard.md",
    }
    atomic_write_text(
        paths["json"], json.dumps(result, indent=2, sort_keys=True) + "\n",
        newline="\n")
    atomic_write_text(
        paths["markdown"], markdown_scorecard(result), newline="\n")
    return paths
