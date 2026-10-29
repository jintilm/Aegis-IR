// Ground truth for rolling-token-v1. Never shipped to the agent workspace.
//
// hash:     FNV-1a 64-bit, offset basis 14695981039346656037, prime
//           1099511628211. (The protected fixture used a slightly different
//           basis; this task deliberately uses the standard one so a model
//           with memorised FNV constants is not penalised.)
// checksum: Adler-32.
// verify:   valid when len >= 8 and hash % 97 == 0.

#include "target.h"

namespace {
constexpr uint64_t kOffset = 14695981039346656037ULL;
constexpr uint64_t kPrime = 1099511628211ULL;
constexpr uint32_t kMod = 65521;
} // namespace

uint64_t bench_hash(const uint8_t *data, size_t len) {
  uint64_t h = kOffset;
  for (size_t i = 0; i < len; ++i) {
    h ^= data[i];
    h *= kPrime;
  }
  return h;
}

uint32_t bench_checksum(const uint8_t *data, size_t len) {
  uint32_t a = 1;
  uint32_t b = 0;
  for (size_t i = 0; i < len; ++i) {
    a = (a + data[i]) % kMod;
    b = (b + a) % kMod;
  }
  return (b << 16) | a;
}

int bench_verify(const uint8_t *data, size_t len) {
  if (len < 8)
    return 0;
  return (bench_hash(data, len) % 97) == 0 ? 1 : 0;
}
