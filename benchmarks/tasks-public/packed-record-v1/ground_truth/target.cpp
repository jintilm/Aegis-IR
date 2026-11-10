// Ground truth for packed-record-v1. Never shipped to the agent workspace.

#include "target.h"

namespace {
constexpr uint8_t kSbox[16] = {6, 11, 1, 9, 14, 2, 13, 7,
                               4, 15, 0, 10, 3, 12, 8, 5};

inline uint64_t rotl64(uint64_t x, unsigned n) {
  return (x << n) | (x >> (64 - n));
}
} // namespace

uint32_t pr_flags(const uint8_t *data, size_t len) {
  uint32_t w = 0;
  const size_t n = len < 4 ? len : 4;
  for (size_t i = 0; i < n; ++i)
    w = (w << 8) | data[i];
  w <<= 8u * static_cast<unsigned>(4 - n);
  const uint32_t mode = (w >> 27) & 0x1Fu;
  const uint32_t lane = (w >> 19) & 0x0Fu;
  const uint32_t span = w & 0x7FFFFu;
  return (mode * 2654435761u) ^ (lane << 13) ^ span;
}

uint64_t pr_fold(const uint8_t *data, size_t len) {
  uint64_t h = 0x243F6A8885A308D3ull;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t b = data[i];
    h ^= static_cast<uint64_t>(kSbox[b & 0x0F]) << ((b >> 4) & 3u);
    h = rotl64(h, 9) * 0x9E3779B97F4A7C15ull;
    h += 0x165667B19E3779F9ull;
  }
  return h ^ (static_cast<uint64_t>(len) * 0xC2B2AE3D27D4EB4Full);
}

int pr_accept(const uint8_t *data, size_t len) {
  if (len < 12)
    return 0;
  const uint32_t f = pr_flags(data, len);
  return (((f >> 3) & 7u) == (static_cast<uint32_t>(len) & 7u)) ? 1 : 0;
}
