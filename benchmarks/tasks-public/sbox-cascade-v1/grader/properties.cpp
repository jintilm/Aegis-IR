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
    expect(sc_scrub(nullptr, 0) == 2851903372u,
           "empty input returns the fixed lane fold");
    expect(sc_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t short_input[4] = {0x12, 0x34, 0x56, 0x78};
    for (size_t len = 0; len < 5; ++len)
      expect(sc_accept(short_input, len) == 0,
             "inputs shorter than five bytes are rejected");

    std::vector<uint8_t> input = {
        0x00, 0x1F, 0x80, 0xAA, 0x55, 0xC3, 0x7E, 0x11};
    expect(sc_scrub(input.data(), input.size()) ==
               sc_scrub(input.data(), input.size()),
           "scrub is deterministic");
    std::vector<uint8_t> swapped = input;
    std::swap(swapped[0], swapped[1]);
    expect(sc_scrub(input.data(), input.size()) !=
               sc_scrub(swapped.data(), swapped.size()),
           "swapping bytes changes the scrub result");

    std::vector<uint8_t> high = {0xF0};
    std::vector<uint8_t> low = {0x0F};
    expect(sc_scrub(high.data(), high.size()) !=
               sc_scrub(low.data(), low.size()),
           "high and low nibbles follow different cascades");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
