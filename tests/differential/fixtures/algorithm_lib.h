// Minimal "offline C++ algorithm library" fixture for the differential
// harness. Functions have external C++ linkage and mangled names, matching
// the primary target scenario: a library shipped separately from its caller.

#ifndef AEGIS_FIXTURE_ALGORITHM_LIB_H
#define AEGIS_FIXTURE_ALGORITHM_LIB_H

#include <cstddef>
#include <cstdint>

// FNV-1a 64-bit rolling hash.
uint64_t rolling_hash(const uint8_t *data, size_t len);

// Adler-32-like checksum.
uint32_t checksum32(const uint8_t *data, size_t len);

// A token is considered valid when it is at least 8 bytes and its rolling
// hash is divisible by 97. Exercise for the policy-driven transform matrix.
bool verify_token(const uint8_t *data, size_t len);

#endif // AEGIS_FIXTURE_ALGORITHM_LIB_H