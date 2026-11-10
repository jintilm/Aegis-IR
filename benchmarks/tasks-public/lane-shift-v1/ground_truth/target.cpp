// Ground truth for lane-shift-v1. Never shipped to the agent workspace.

#include "target.h"

namespace {
constexpr uint32_t kSeed = 0x811C9DC5u;
constexpr uint8_t kNib[16] = {0x3, 0xE, 0x1, 0xA, 0x8, 0x5, 0xD, 0x0,
                              0xB, 0x6, 0x9, 0xF, 0x2, 0xC, 0x7, 0x4};

inline uint32_t rotl32(uint32_t x, unsigned n) {
  n &= 31u;
  return n == 0 ? x : (x << n) | (x >> (32 - n));
}
} // namespace

uint32_t ls_mix(const uint8_t *data, size_t len) {
  uint32_t a = kSeed;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t b = data[i];
    a ^= (static_cast<uint32_t>(kNib[b & 0x0F]) << 4) |
         kNib[(b >> 4) & 0x0F];
    a = rotl32(a, 5) * 0x01000193u;
    a += static_cast<uint32_t>(i) * 0x9E3779B9u;
  }
  return a ^ (static_cast<uint32_t>(len) * 0x85EBCA6Bu);
}

uint32_t ls_window(const uint8_t *data, size_t len, uint32_t start) {
  if (len == 0)
    return 0;
  const size_t base = static_cast<size_t>(start % len);
  uint32_t acc = 0;
  for (size_t k = 0; k < 5; ++k) {
    const size_t idx = (base + k) % len;
    acc = rotl32(acc ^ data[idx], static_cast<unsigned>(k) + 1);
  }
  return acc;
}

int ls_accept(const uint8_t *data, size_t len) {
  if (len < 5)
    return 0;
  return (ls_mix(data, len) % 29u) ==
                 (static_cast<uint32_t>(data[0]) % 29u)
             ? 1
             : 0;
}
