# Aegis-Bench (main product, in development)

This directory will hold the benchmark harness: agent adapters (C1-C3 red
teams + the white-box attacker), task runner with fixed budgets, independent
grader, and report generator.

Nothing is implemented yet. The protocol is specified in
[`docs/benchmark-protocol.md`](../../docs/benchmark-protocol.md); task format
and directory layout are still being drafted. First milestone: a static C1
adapter plus grader that can score one fixture end to end.

Design constraints:

- no model API keys or network access in build/CI paths;
- scores come from executing candidates against hidden property tests, never
  from text similarity;
- every result row carries model version, budget config, and commit hash.
