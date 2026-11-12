#include "target.h"

#include <cstdio>
#include <utility>
#include <vector>

namespace {
int failures = 0;

void expect(bool condition, const char *message) {
  if (!condition) {
    std::fprintf(stderr, "PROPERTY FAIL: %s\n", message);
    ++failures;
  }
}
} // namespace

struct PropertyChecks {
  PropertyChecks() {
    expect(dl_score(nullptr, 0) == 0x3C6EF372u,
           "empty input returns the seed");
    expect(dl_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t short_input[6] = {1, 2, 3, 4, 5, 6};
    for (size_t len = 0; len < 7; ++len)
      expect(dl_accept(short_input, len) == 0,
             "inputs shorter than seven bytes are rejected");

    std::vector<uint8_t> input = {
        0x01, 0x7F, 0x42, 0xE5, 0x2A, 0x9C, 0x13, 0x5D};
    expect(dl_score(input.data(), input.size()) ==
               dl_score(input.data(), input.size()),
           "score is deterministic");
    std::vector<uint8_t> swapped = input;
    std::swap(swapped[0], swapped[1]);
    expect(dl_score(input.data(), input.size()) !=
               dl_score(swapped.data(), swapped.size()),
           "swapping the first bytes changes the score");

    std::vector<uint8_t> one = {0x40};
    expect(dl_score(one.data(), one.size()) != dl_score(nullptr, 0),
           "one tagged byte advances the seed");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
