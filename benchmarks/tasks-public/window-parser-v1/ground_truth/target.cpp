#include "target.h"

namespace {
constexpr uint32_t kSeed = 0xA5F1C39Bu;

inline uint32_t rotl32(uint32_t x, unsigned n) {
  n &= 31u;
  return n == 0 ? x : (x << n) | (x >> (32 - n));
}
} // namespace

uint32_t wp_parse(const uint8_t *data, size_t len) {
  uint32_t state = kSeed;
  uint32_t mode = 0;
  size_t pos = 0;
  while (pos < len) {
    const uint8_t byte = data[pos++];
    const uint32_t tag = (byte >> 5) & 7u;
    const uint32_t payload = byte & 0x1Fu;
    if (tag == 0) {
      mode = (mode + payload + 1u) & 0xFFu;
      state ^= mode * 0x9E3779B1u;
    } else if (tag == 1) {
      state = rotl32(state, (payload & 15u) + 3u) ^
              (payload * 0x85EBCA6Bu);
    } else if (tag == 2) {
      state += payload * 0x27D4EB2Fu;
    } else if (tag == 3) {
      state ^= (mode << 13) + payload;
    } else {
      size_t take = tag - 3u;
      if (take > len - pos)
        take = len - pos;
      uint32_t word = 0;
      for (size_t i = 0; i < take; ++i)
        word = (word << 8) | data[pos++];
      state = rotl32(state, tag) + word * 0xC2B2AE35u;
    }
    mode = (mode * 33u + payload + tag) & 0xFFu;
    state = state * 0x01000193u + 0x165667B1u +
            static_cast<uint32_t>(pos);
    if (tag == 7)
      break;
  }
  return state ^ (static_cast<uint32_t>(len) * 0x9FB21C65u);
}

int wp_accept(const uint8_t *data, size_t len) {
  if (len < 6)
    return 0;
  return ((wp_parse(data, len) & 31u) ==
          ((static_cast<uint32_t>(data[0]) ^
            static_cast<uint32_t>(len)) &
           31u))
             ? 1
             : 0;
}
