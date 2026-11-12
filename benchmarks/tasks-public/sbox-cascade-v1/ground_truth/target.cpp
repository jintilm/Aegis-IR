#include "target.h"

namespace {
constexpr uint32_t kSeed = 0x6D2B79F5u;

inline uint32_t rotl32(uint32_t value, unsigned shift) {
  shift &= 31u;
  return shift == 0 ? value
                    : (value << shift) | (value >> (32 - shift));
}

uint32_t next_random(uint32_t &state) {
  state ^= state << 13;
  state ^= state >> 17;
  state ^= state << 5;
  return state;
}
} // namespace

uint32_t sc_scrub(const uint8_t *data, size_t len) {
  uint8_t box[16];
  uint32_t random = kSeed;
  for (uint32_t i = 0; i < 16; ++i) {
    const uint32_t value = next_random(random);
    box[i] = static_cast<uint8_t>(
        ((value >> (i & 15u)) ^ (value >> 7) ^ i * 13u) & 15u);
  }

  uint32_t lanes[4] = {
      kSeed, 0x9E3779B9u, 0x85EBCA6Bu, 0xC2B2AE35u};
  uint8_t prior = 0;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t byte = data[i];
    const uint8_t index =
        static_cast<uint8_t>(((byte >> 4) ^ prior) & 15u);
    const uint8_t substituted = box[index];
    const uint8_t lane = static_cast<uint8_t>((byte ^ i) & 3u);
    lanes[lane] ^= rotl32(
        static_cast<uint32_t>(substituted) * 0x9E3779B1u + byte,
        (static_cast<unsigned>(i) + substituted) & 15u);
    lanes[(lane + 1u) & 3u] = rotl32(
        lanes[(lane + 1u) & 3u] +
            static_cast<uint32_t>(byte & 15u) * 0x27D4EB2Fu,
        (static_cast<unsigned>(i) & 7u) + 1u);
    prior = static_cast<uint8_t>(
        box[(byte & 15u) ^ (lanes[lane] & 15u)] ^ substituted);
    lanes[3] += prior + static_cast<uint32_t>(i) * 0x01000193u;
    if ((i & 3u) == 3u) {
      lanes[0] ^= rotl32(lanes[2], 13);
      lanes[1] += lanes[0] ^ lanes[3];
      lanes[2] = rotl32(lanes[2] + lanes[1], 7);
    }
  }
  uint32_t result = lanes[0] ^ rotl32(lanes[1], 5) ^
                    rotl32(lanes[2], 11) ^ rotl32(lanes[3], 17);
  return result ^ static_cast<uint32_t>(len) * 0x9FB21C65u;
}

int sc_accept(const uint8_t *data, size_t len) {
  if (len < 5)
    return 0;
  const uint32_t expected =
      (static_cast<uint32_t>(data[0]) * 3u +
       static_cast<uint32_t>(data[len - 1]) +
       static_cast<uint32_t>(len)) &
      15u;
  return (sc_scrub(data, len) & 15u) == expected ? 1 : 0;
}
