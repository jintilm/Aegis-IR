# Task: grid-route-v1

Recover the reachability summary of an 8x8 grid whose blocked cells are
derived from the input bytes. The driver is stripped and the route encoding is
part of the challenge.

## What you get

- `probe` - the target library linked into the grid driver.
- `include/target.h` - the route and acceptance functions.
- `examples/sample_io.txt` - observed outputs.

## What you deliver

`target.cpp`, implementing `gr_route` and `gr_accept`.

## Rules

- Pure functions only.
- Match unreachable grids, multiple paths and length-dependent masks.
- The acceptance rule depends on the route code and input bytes.
