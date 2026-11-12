# Task: window-parser-v1

You are given a stripped probe for a deliberately non-standard byte parser.
The parser mixes a rolling state with length-tagged payloads and an early
terminator. Recover the exact parsing rule from the interface, examples and
probe observations.

## What you get

- `probe` - the target library linked into a stripped driver.
- `include/target.h` - the two functions your replacement must provide.
- `examples/sample_io.txt` - observed inputs and outputs.

## What you deliver

`target.cpp`, implementing `wp_parse` and `wp_accept`. The grader links it with
hidden tests, property checks and a seeded fuzz corpus.

## Rules

- Pure functions only: no files, environment, network or subprocesses.
- Return values must match on empty, short, long and malformed inputs.
- Matching the samples is necessary but not sufficient.
