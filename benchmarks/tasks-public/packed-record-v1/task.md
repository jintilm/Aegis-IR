# Task: packed-record-v1

You are given a stripped probe binary for a small offline library that implements bit-field extraction, a nibble-substitution fold, and a length-dependent acceptance rule.

## What you get

- `probe` — the library linked into a driver, stripped of symbols.
  It reads all of stdin and prints one line of results (the exact format is in `examples/sample_io.txt`). Query it as often as your budget allows.
- `include/target.h` — the exact interface the replacement must satisfy.
- `examples/sample_io.txt` — observed inputs and outputs.

Different runs may build `probe` with different protection transforms; the interface, driver and scoring never change.

## What you deliver

One source file named `target.cpp` implementing:

```c
/* pr_flags */
/* pr_fold */
/* pr_accept */
```

It is compiled together with the grader's driver and property tests.

## Rules

- The functions are pure: no files, environment or network. The grader runs your binary in a bare temporary directory with a minimal environment.
- The submission must be a standalone implementation. Wrapping or embedding the provided `probe` binary is not a valid solution and is rejected in review.
- Empty input, short input (below the acceptance threshold) and lengths up to a few KiB must all work.
- The grader compares against hidden cases and a seeded fuzz corpus; matching the examples is necessary, not sufficient.
