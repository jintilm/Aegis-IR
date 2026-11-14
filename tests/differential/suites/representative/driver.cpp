#include "algorithm_lib.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

namespace {
constexpr std::size_t kMinimumWorkBytes = 1024 * 1024;
constexpr std::size_t kPasses = 8;
constexpr std::size_t kRecordCapacity = 4096;

int g_propertyFailures = 0;

void expect(bool condition, const char *what) {
  if (!condition) {
    std::fprintf(stderr, "PROPERTY FAIL: %s\n", what);
    ++g_propertyFailures;
  }
}

std::vector<std::uint8_t> expand_input(const std::vector<std::uint8_t> &input) {
  const std::size_t scaled = input.size() * 48;
  const std::size_t size =
      scaled > kMinimumWorkBytes ? scaled : kMinimumWorkBytes;
  std::vector<std::uint8_t> expanded(size);
  std::uint32_t state = 0x6d2b79f5u;
  for (std::size_t i = 0; i < size; ++i) {
    if (!input.empty() && (i % 5) != 0)
      expanded[i] = input[i % input.size()];
    else {
      state ^= state << 13;
      state ^= state >> 17;
      state ^= state << 5;
      expanded[i] = static_cast<std::uint8_t>(state);
    }
  }
  return expanded;
}
} // namespace

int main() {
  std::vector<std::uint8_t> input;
  std::uint8_t buffer[4096];
  std::size_t read = 0;
  while ((read = std::fread(buffer, 1, sizeof(buffer), stdin)) > 0)
    input.insert(input.end(), buffer, buffer + read);

  const std::vector<std::uint8_t> workload = expand_input(input);
  expect(aegis_rep_parse(nullptr, 0, nullptr, 0) == 0, "empty parser input");
  expect(aegis_rep_fold(nullptr, 0) == 0xcbf29ce484222325ULL,
         "fold empty state");

  std::uint32_t records[kRecordCapacity];
  std::uint64_t digest = 0;
  std::uint64_t folded = 0;
  std::uint64_t rounds = 0;
  std::size_t total_records = 0;

  for (std::size_t pass = 0; pass < kPasses; ++pass) {
    const std::size_t count =
        aegis_rep_parse(workload.data() + pass * 17,
                        workload.size() - pass * 17, records, kRecordCapacity);
    total_records += count;
    folded = aegis_rep_fold(records, count);
    rounds = aegis_rep_rounds(folded ^ pass, records, count);
    digest ^= aegis_rep_digest(records, count, rounds);
  }

  expect(
      digest ==
          [&]() {
            std::uint32_t check = 0;
            for (std::size_t pass = 0; pass < kPasses; ++pass) {
              const std::size_t count = aegis_rep_parse(
                  workload.data() + pass * 17, workload.size() - pass * 17,
                  records, kRecordCapacity);
              const std::uint64_t check_fold = aegis_rep_fold(records, count);
              const std::uint64_t check_rounds =
                  aegis_rep_rounds(check_fold ^ pass, records, count);
              check ^= aegis_rep_digest(records, count, check_rounds);
            }
            return static_cast<std::uint64_t>(check);
          }(),
      "digest deterministic");

  std::printf(
      "input=%zu work=%zu records=%zu digest=%llu folded=%llu rounds=%llu\n",
      input.size(), workload.size(), total_records,
      static_cast<unsigned long long>(digest),
      static_cast<unsigned long long>(folded),
      static_cast<unsigned long long>(rounds));

  if (g_propertyFailures != 0) {
    std::fprintf(stderr, "%d property failure(s)\n", g_propertyFailures);
    return 3;
  }
  return 0;
}
