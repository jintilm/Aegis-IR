#include "algorithm_lib.h"

namespace {
constexpr std::uint64_t kOffset = 0xcbf29ce484222325ULL;
constexpr std::uint64_t kPrime = 0x100000001b3ULL;

std::uint64_t mix(std::uint64_t value) {
  value ^= value >> 30;
  value *= 0xbf58476d1ce4e5b9ULL;
  value ^= value >> 27;
  value *= 0x94d049bb133111ebULL;
  return value ^ (value >> 31);
}
} // namespace

extern "C" std::size_t aegis_rep_parse(const std::uint8_t *data,
                                       std::size_t len, std::uint32_t *records,
                                       std::size_t capacity) {
  if (data == nullptr || records == nullptr || capacity == 0)
    return 0;

  std::size_t count = 0;
  std::uint32_t accumulator = 0x811c9dc5u;
  unsigned digits = 0;
  for (std::size_t i = 0; i < len; ++i) {
    const std::uint8_t byte = data[i];
    if (byte == '|' || byte == ';' || byte == '\n' || byte == '\r') {
      if (count < capacity)
        records[count++] = accumulator;
      accumulator = 0x811c9dc5u;
      digits = 0;
      continue;
    }
    if (byte >= '0' && byte <= '9' && digits < 9) {
      accumulator = accumulator * 10u + (byte - '0');
      ++digits;
    } else {
      accumulator = (accumulator << 5) ^ (accumulator >> 2) ^ byte;
      digits = 0;
    }
  }
  if (digits != 0 && count < capacity)
    records[count++] = accumulator;
  return count;
}

extern "C" std::uint64_t aegis_rep_fold(const std::uint32_t *records,
                                        std::size_t count) {
  if (records == nullptr)
    return kOffset;

  std::uint64_t state = kOffset;
  std::uint64_t counts[4] = {0, 0, 0, 0};
  for (std::size_t i = 0; i < count; ++i) {
    const std::uint32_t record = records[i];
    const unsigned lane = record & 3u;
    counts[lane] += record + i;
    state ^= static_cast<std::uint64_t>(record) + i;
    state *= kPrime;
    state ^= state >> 17;
  }
  state ^= counts[0] * 3 + counts[1] * 5 + counts[2] * 7 + counts[3] * 11;
  return mix(state);
}

extern "C" std::uint64_t aegis_rep_rounds(std::uint64_t seed,
                                          const std::uint32_t *records,
                                          std::size_t count) {
  if (records == nullptr)
    return seed;

  std::uint64_t state = seed ^ (static_cast<std::uint64_t>(count) << 32);
  for (unsigned round = 0; round < 12; ++round) {
    for (std::size_t i = 0; i < count; ++i) {
      const std::uint64_t value =
          static_cast<std::uint64_t>(records[i]) + (i << 1) + round;
      state ^= value * kPrime;
      state = (state << 7) | (state >> 57);
      switch (value & 3u) {
      case 0:
        state += 0x9e3779b97f4a7c15ULL;
        break;
      case 1:
        state ^= state >> 23;
        break;
      case 2:
        state += state << 13;
        break;
      default:
        state ^= 0xd6e8feb86659fd93ULL;
        break;
      }
    }
  }
  return mix(state);
}

extern "C" std::uint32_t aegis_rep_digest(const std::uint32_t *records,
                                          std::size_t count,
                                          std::uint64_t folded) {
  if (records == nullptr)
    return static_cast<std::uint32_t>(folded);

  std::uint32_t a = 1;
  std::uint32_t b = 0;
  for (std::size_t i = 0; i < count; ++i) {
    a = (a + records[i] + static_cast<std::uint32_t>(i)) % 65521u;
    b = (b + a) % 65521u;
  }
  a ^= static_cast<std::uint32_t>(folded >> 32);
  b ^= static_cast<std::uint32_t>(folded);
  return (b << 16) | a;
}
