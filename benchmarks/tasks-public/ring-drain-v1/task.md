# Task: ring-drain-v1

Recover the semantics of a command stream interpreted by a small ring buffer.
Commands overwrite, drain and reset a capacity-limited structure while a
rolling hash records the evicted values.

## What you get

- `probe` - the stripped target library and its driver.
- `include/target.h` - the ring and acceptance interface.
- `examples/sample_io.txt` - real observations.

## What you deliver

`target.cpp`, implementing `rd_ring` and `rd_accept`.

## Rules

- Pure functions only.
- Preserve queue order, wraparound, capacity clamping and reset behavior.
- Capacity zero, short streams and malformed command sequences must match.
