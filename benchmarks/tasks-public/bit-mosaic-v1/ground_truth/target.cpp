#include "target.h"

namespace {
constexpr uint32_t kSeed = 0xB7E15163u;

inline uint32_t rotl32(uint32_t value, unsigned shift) {
  shift &= 31u;
  return shift == 0 ? value
                    : (value << shift) | (value >> (32 - shift));
}

inline uint32_t parity32(uint32_t value) {
  value ^= value >> 16;
  value ^= value >> 8;
  value ^= value >> 4;
  value &= 0xFu;
  return (0x6996u >> value) & 1u;
}
} // namespace

uint32_t bm_mosaic(const uint8_t *data, size_t len) {
  uint32_t lanes[4] = {
      kSeed, 0x243F6A88u, 0x85A308D3u, 0x13198A2Eu};
  uint32_t parity = 0;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t byte = data[i];
    const uint32_t lane = (byte >> 6) & 3u;
    const uint32_t row = (byte >> 3) & 7u;
    const uint32_t column = byte & 7u;
    const uint32_t source =
        (lanes[lane] >> ((byte + i) & 31u)) & 1u;
    const uint32_t cell =
        row * 8u + ((column + source) & 7u);
    lanes[lane] ^= (cell + 1u) * 0x9E3779B1u + byte;
    lanes[(lane + 1u) & 3u] = rotl32(
        lanes[(lane + 1u) & 3u] +
            static_cast<uint32_t>(byte & 31u) * 0x27D4EB2Fu,
        (static_cast<unsigned>(i) & 15u) + 1u);
    if (source)
      lanes[(lane + 2u) & 3u] += lanes[lane] ^ 0xA5A5A5A5u;
    parity ^= parity32(
        lanes[lane] ^ static_cast<uint32_t>(i * 17u + cell));
    if ((i & 3u) == 3u) {
      lanes[0] ^= rotl32(lanes[3], 7);
      lanes[1] = rotl32(lanes[1] + lanes[0], 11);
      lanes[2] ^= lanes[1] * 0x01000193u;
      lanes[3] += parity * 0xC2B2AE35u;
    }
  }
  return lanes[0] ^ rotl32(lanes[1], 7) ^
         rotl32(lanes[2], 13) ^ rotl32(lanes[3], 21) ^
         parity ^ static_cast<uint32_t>(len) * 0x9FB21C65u;
}

int bm_accept(const uint8_t *data, size_t len) {
  if (len < 6)
    return 0;
  const uint32_t expected =
      (static_cast<uint32_t>(data[0]) +
       static_cast<uint32_t>(data[len - 1]) * 3u +
       static_cast<uint32_t>(len)) &
      15u;
  return (bm_mosaic(data, len) & 15u) == expected ? 1 : 0;
}
