# Cascaded S-box

Recover `sc_scrub` and `sc_accept`.

The implementation derives a sixteen-entry nibble substitution table from a
fixed seed, then uses the prior substituted nibble to choose the next lookup.
Rotation, byte position, and a four-byte lane mix feed the final score.

Implement `target.cpp` against `include/target.h`. Hidden cases and seeded fuzz
inputs are used for grading.
