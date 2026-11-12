#include "target.h"

namespace {
constexpr uint32_t kSeed = 0x3C6EF372u;

inline uint32_t rotl32(uint32_t value, unsigned shift) {
  shift &= 31u;
  return shift == 0 ? value
                    : (value << shift) | (value >> (32 - shift));
}
} // namespace

uint32_t dl_score(const uint8_t *data, size_t len) {
  uint32_t state = kSeed;
  uint32_t ledger = 0;
  uint32_t count = 0;
  uint8_t prior = 0x5A;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t byte = data[i];
    const uint32_t op = byte >> 6;
    const uint32_t payload = byte & 63u;
    if (op == 0) {
      const int32_t delta = static_cast<int32_t>(payload & 31u) - 16;
      ledger += static_cast<uint32_t>(delta) * 0x9E3779B1u;
      state ^= rotl32(ledger, payload & 7u);
    } else if (op == 1) {
      state = rotl32(state ^ payload * 0xC2B2AE35u,
                     (payload % 17u) + 1u) +
              ledger;
    } else if (op == 2) {
      ++count;
      ledger += (state >> 24) + payload;
      state ^= count * 0x27D4EB2Fu;
    } else {
      prior = static_cast<uint8_t>(payload * 33u + prior);
      state += (static_cast<uint32_t>(prior) ^ 0x85EBCA6Bu) *
               0x01000193u;
    }
    state = rotl32(state, (byte >> 3) & 7u) +
            static_cast<uint32_t>(i) + byte;
    ledger ^= state >> 13;
  }
  return state ^ ledger ^
         (static_cast<uint32_t>(len) * 0x9FB21C65u);
}

int dl_accept(const uint8_t *data, size_t len) {
  if (len < 7)
    return 0;
  const uint32_t expected =
      (static_cast<uint32_t>(data[0]) ^
       static_cast<uint32_t>(data[len - 1]) ^
       static_cast<uint32_t>(len)) &
      31u;
  return (dl_score(data, len) & 31u) == expected ? 1 : 0;
}
