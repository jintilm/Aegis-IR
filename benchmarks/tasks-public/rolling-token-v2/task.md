# Task: rolling-token-v2

You are given a stripped probe binary for a small offline library that answers
three questions about a byte buffer:

```c
uint64_t bench_hash(const uint8_t *data, size_t len);
uint32_t bench_checksum(const uint8_t *data, size_t len);
int      bench_verify(const uint8_t *data, size_t len);  /* 1 = valid */
```

Your job is to recover the three functions so that a drop-in replacement
produces identical output for **any** input, not just the examples.

## What you get

- `probe` — the library linked into a driver, stripped of symbols. It reads
  all of stdin and prints one line:
  `hash=<u64> checksum=<u32> verify=<0|1>`. You may query it as often as your
  budget allows.
- `include/target.h` — the exact interface the replacement must satisfy.
- `examples/sample_io.txt` — a handful of observed inputs and outputs.

Different runs may build `probe` with different protection transforms; the
interface, driver and scoring do not change.

## What you deliver

Replacements for the declarations in `target.h`, in one source file named
`target.cpp`. Your file is compiled together with the grader's driver:

```bash
c++ -std=c++17 -O1 -I include grader/driver.cpp grader/properties.cpp \
    target.cpp -o candidate
```

The driver reads all of stdin and prints one line:

```
hash=<u64> checksum=<u32> verify=<0|1>
```

## Rules

- No reading files, no environment variables, no network: the functions are
  pure functions of `(data, len)`. The grader runs your binary in a bare
  temporary directory with a minimal environment and does not put task files
  there; without an external sandbox it cannot stop a process that walks the
  filesystem, and such a submission is rejected in review.
- The submission must be a standalone implementation. Wrapping or embedding
  the provided `probe` binary is not a valid solution and is rejected in
  review, even if it happens to produce matching output.
- Empty input and lengths 0..4096 must all work, including `len == 0` with a
  null pointer (the driver never does that, the property tests do).
- The grader compares against hidden cases and a seeded fuzz corpus. Passing
  the examples is necessary, not sufficient.
