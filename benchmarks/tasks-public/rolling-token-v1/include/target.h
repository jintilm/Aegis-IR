#pragma once

#include <cstddef>
#include <cstdint>

// Recover these three functions from the protected library.
//
// The library computes deterministic values over a byte buffer. All three
// functions are pure: the result depends only on (data, len).

uint64_t bench_hash(const uint8_t *data, size_t len);

uint32_t bench_checksum(const uint8_t *data, size_t len);

// Returns 1 when the buffer is a valid token, 0 otherwise.
int bench_verify(const uint8_t *data, size_t len);
