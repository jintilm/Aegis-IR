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
    expect(pw_weave(nullptr, 0) == 28399398u,
           "empty input returns the fixed lane fold");
    expect(pw_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t short_input[7] = {0, 1, 2, 3, 4, 5, 6};
    for (size_t len = 0; len < 8; ++len)
      expect(pw_accept(short_input, len) == 0,
             "inputs shorter than eight bytes are rejected");

    std::vector<uint8_t> input = {
        0x12, 0x34, 0xA5, 0x5A, 0xFF, 0x00, 0x7E, 0x81, 0x33};
    expect(pw_weave(input.data(), input.size()) ==
               pw_weave(input.data(), input.size()),
           "weave is deterministic");
    std::vector<uint8_t> swapped = input;
    std::swap(swapped[0], swapped[1]);
    expect(pw_weave(input.data(), input.size()) !=
               pw_weave(swapped.data(), swapped.size()),
           "swapping bytes within a word changes the weave");

    std::vector<uint8_t> even = {0x12, 0x34, 0x56, 0x78};
    std::vector<uint8_t> odd = even;
    odd.push_back(0x9A);
    expect(pw_weave(even.data(), even.size()) !=
               pw_weave(odd.data(), odd.size()),
           "an odd-byte tail changes the weave");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
