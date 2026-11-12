# Packet weave

Recover `pw_weave` and `pw_accept`.

The input is consumed as big-endian 16-bit words interleaved with an odd-byte
tail. Each word is XOR-masked by position, rotated by a derived nibble, and
folded into two accumulators. Short inputs and truncated tails follow the same
deterministic path.

Implement `target.cpp` against `include/target.h`. Hidden cases and seeded fuzz
inputs are used for grading.
