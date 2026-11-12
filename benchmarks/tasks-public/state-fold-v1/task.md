# Task: state-fold-v1

Recover a stateful integer mixer and the rolling digest built on top of it.
The transition is deliberately non-standard and includes token-dependent
rotation and avalanche transforms.

## What you get

- `probe` - a stripped driver linked to the target library.
- `include/target.h` - the exact transition, digest and acceptance interface.
- `examples/sample_io.txt` - observed outputs.

## What you deliver

`target.cpp`, implementing `sf_step`, `sf_digest` and `sf_accept`.

## Rules

- Pure functions only.
- Preserve exact unsigned 64-bit wraparound.
- Empty, partial and multi-kilobyte inputs are all graded.
