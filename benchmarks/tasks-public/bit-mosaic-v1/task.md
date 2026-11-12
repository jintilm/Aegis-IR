# Bit mosaic

Recover `bm_mosaic` and `bm_accept`.

Each byte selects a lane, a row, a column, and a source bit. Lanes are rotated
and cross-mixed on a fixed schedule, with a parity fold inserted every fourth
byte. The acceptance predicate compares the folded low bits with the first and
last bytes.

Implement `target.cpp` against `include/target.h`. Hidden cases and seeded fuzz
inputs are used for grading.
