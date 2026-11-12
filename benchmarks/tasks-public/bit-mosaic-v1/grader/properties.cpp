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
    expect(bm_mosaic(nullptr, 0) == 2357987060u,
           "empty input returns the fixed lane fold");
    expect(bm_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t short_input[5] = {0, 1, 2, 3, 4};
    for (size_t len = 0; len < 6; ++len)
      expect(bm_accept(short_input, len) == 0,
             "inputs shorter than six bytes are rejected");

    std::vector<uint8_t> input = {
        0x00, 0x3F, 0x80, 0xFF, 0x55, 0xAA, 0x12, 0x34};
    expect(bm_mosaic(input.data(), input.size()) ==
               bm_mosaic(input.data(), input.size()),
           "mosaic is deterministic");
    std::vector<uint8_t> swapped = input;
    std::swap(swapped[0], swapped[1]);
    expect(bm_mosaic(input.data(), input.size()) !=
               bm_mosaic(swapped.data(), swapped.size()),
           "swapping bytes changes the mosaic");

    std::vector<uint8_t> prefix = {0xC1, 0xC2, 0xC3};
    std::vector<uint8_t> extended = prefix;
    extended.push_back(0x2A);
    expect(bm_mosaic(prefix.data(), prefix.size()) !=
               bm_mosaic(extended.data(), extended.size()),
           "a fourth byte triggers the cross-lane fold");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
