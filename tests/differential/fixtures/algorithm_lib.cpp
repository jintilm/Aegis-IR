// Fixture algorithm library. Protected translation unit in the differential
// matrix; the driver below is always built unprotected.

#include "algorithm_lib.h"

namespace {
constexpr uint64_t kFnvOffsetBasis = 1469598103934665603ULL;
constexpr uint64_t kFnvPrime = 1099511628211ULL;
constexpr uint32_t kAdlerMod = 65521;
} // namespace

uint64_t rolling_hash(const uint8_t *data, size_t len) {
  uint64_t h = kFnvOffsetBasis;
  for (size_t i = 0; i < len; ++i) {
    h ^= data[i];
    h *= kFnvPrime;
  }
  return h;
}

uint32_t checksum32(const uint8_t *data, size_t len) {
  uint32_t a = 1;
  uint32_t b = 0;
  for (size_t i = 0; i < len; ++i) {
    a = (a + data[i]) % kAdlerMod;
    b = (b + a) % kAdlerMod;
  }
  return (b << 16) | a;
}

bool verify_token(const uint8_t *data, size_t len) {
  if (len < 8)
    return false;
  return (rolling_hash(data, len) % 97) == 0;
}