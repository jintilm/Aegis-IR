#include "target.h"

namespace {
inline uint64_t rotl64(uint64_t x, unsigned n) {
  n &= 63u;
  return n == 0 ? x : (x << n) | (x >> (64 - n));
}
} // namespace

uint64_t sf_step(uint64_t state, uint32_t token) {
  uint64_t x = state ^
               (static_cast<uint64_t>(token) * 0xD6E8FEB86659FD93ull);
  x ^= x >> 33;
  x *= 0xFF51AFD7ED558CCDull;
  x ^= x >> 33;
  x *= 0xC4CEB9FE1A85EC53ull;
  x ^= x >> 33;
  return rotl64(x, (token & 63u) + 1u) ^ 0xA24BAED4963EE407ull;
}

uint32_t sf_digest(const uint8_t *data, size_t len) {
  uint64_t state = 0x6A09E667F3BCC909ull;
  for (size_t i = 0; i < len; ++i) {
    uint32_t token = data[i] ^
                     static_cast<uint32_t>(i) * 0x9E3779B1u;
    state = sf_step(state, token);
  }
  state ^= static_cast<uint64_t>(len) * 0x9E3779B97F4A7C15ull;
  return static_cast<uint32_t>(state ^ (state >> 32));
}

int sf_accept(const uint8_t *data, size_t len) {
  if (len < 9)
    return 0;
  const uint32_t tag = (sf_digest(data, len) ^
                        (static_cast<uint32_t>(data[0]) << 24)) &
                       15u;
  return tag == ((static_cast<uint32_t>(len) * 7u) & 15u) ? 1 : 0;
}
