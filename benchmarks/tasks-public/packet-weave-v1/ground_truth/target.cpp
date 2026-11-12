#include "target.h"

namespace {
constexpr uint32_t kSeed = 0xA54FF53Au;

inline uint32_t rotl32(uint32_t value, unsigned shift) {
  shift &= 31u;
  return shift == 0 ? value
                    : (value << shift) | (value >> (32 - shift));
}
} // namespace

uint32_t pw_weave(const uint8_t *data, size_t len) {
  uint32_t low = kSeed;
  uint32_t high = 0x510E527Fu;
  size_t index = 0;
  uint32_t word_index = 0;
  while (index + 1 < len) {
    const uint32_t word =
        (static_cast<uint32_t>(data[index]) << 8) |
        static_cast<uint32_t>(data[index + 1]);
    const uint32_t mask =
        word_index * 0x9E3779B1u + len * 0x85EBCA6Bu;
    const uint32_t mixed = word ^ mask;
    const uint32_t nibble = (mixed >> ((word_index * 5u) & 15u)) & 15u;
    low = rotl32(low + mixed, nibble + 3u) ^
          (mask >> 7);
    high ^= rotl32(mixed * 0xC2B2AE35u, (nibble & 7u) + 1u);
    high += low ^ (word_index * 0x27D4EB2Fu);
    if ((word_index & 1u) != 0) {
      low ^= rotl32(high, 13);
      high = rotl32(high + low, 7);
    }
    index += 2;
    ++word_index;
  }
  uint32_t tail = 0;
  if (index < len) {
    tail = static_cast<uint32_t>(data[index]) * 0x01000193u +
           word_index * 0x9FB21C65u;
    low ^= tail;
    high = rotl32(high + tail, 11);
  }
  return low ^ rotl32(high, 17) ^
         (static_cast<uint32_t>(len) * 0x165667B1u);
}

int pw_accept(const uint8_t *data, size_t len) {
  if (len < 8)
    return 0;
  const uint32_t expected =
      (static_cast<uint32_t>(data[0]) +
       static_cast<uint32_t>(data[1]) * 3u +
       static_cast<uint32_t>(data[len - 2]) * 5u +
       static_cast<uint32_t>(data[len - 1]) +
       static_cast<uint32_t>(len)) &
      31u;
  return (pw_weave(data, len) & 31u) == expected ? 1 : 0;
}
