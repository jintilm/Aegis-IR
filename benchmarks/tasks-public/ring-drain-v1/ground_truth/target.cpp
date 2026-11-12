#include "target.h"

namespace {
inline uint32_t rotl32(uint32_t x, unsigned n) {
  n &= 31u;
  return n == 0 ? x : (x << n) | (x >> (32 - n));
}
} // namespace

uint32_t rd_ring(const uint8_t *data, size_t len, uint32_t cap) {
  cap = cap == 0 ? 8u : (cap > 64u ? 64u : cap);
  uint8_t ring[64] = {};
  uint32_t head = 0;
  uint32_t count = 0;
  uint32_t acc = 0x811C9DC5u;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t byte = data[i];
    const uint32_t op = byte >> 6;
    const uint32_t val = byte & 63u;
    if (op == 0) {
      if (count < cap) {
        ring[(head + count) % cap] = static_cast<uint8_t>(val);
        ++count;
      } else {
        const uint8_t old = ring[head];
        ring[head] = static_cast<uint8_t>(val);
        head = (head + 1u) % cap;
        acc = rotl32(acc ^ (old * 0x9E3779B1u), 7) * 0x01000193u;
      }
    } else if (op == 1) {
      if (count) {
        const uint8_t old = ring[head];
        head = (head + 1u) % cap;
        --count;
        acc = rotl32(acc ^ (old * 0x85EBCA6Bu), 11) * 0x27D4EB2Fu;
      } else {
        acc ^= 0xA5A5A5A5u + val;
      }
    } else if (op == 2) {
      acc ^= (val * 0xC2B2AE35u) + count;
      head = 0;
      count = 0;
    } else {
      acc = rotl32(acc + val * 0x9FB21C65u, (val & 31u) + 1u);
    }
    acc = acc * 33u + val + static_cast<uint32_t>(i) + count;
  }
  return acc ^ (head * 0x9E3779B9u) ^ (count * 0x7F4A7C15u);
}

int rd_accept(const uint8_t *data, size_t len) {
  if (len < 8)
    return 0;
  const uint32_t cap = 1u + (data[0] & 63u);
  return (rd_ring(data, len, cap) % 23u) == (data[len - 1] % 23u) ? 1 : 0;
}
