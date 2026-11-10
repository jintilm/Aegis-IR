// Independent property tests for lane-shift-v1.

#include "target.h"

#include <cstdio>
#include <vector>

namespace {
int g_failures = 0;

void expect(bool cond, const char *what) {
  if (!cond) {
    std::fprintf(stderr, "PROPERTY FAIL: %s\n", what);
    ++g_failures;
  }
}
} // namespace

struct PropertyChecks {
  PropertyChecks() {
    expect(ls_mix(nullptr, 0) == 0x811C9DC5u, "mix of empty input is the seed");
    expect(ls_window(nullptr, 0, 0) == 0, "empty window is 0");
    expect(ls_accept(nullptr, 0) == 0, "empty buffer is rejected");

    const uint8_t shortbuf[4] = {9, 8, 7, 6};
    for (size_t len = 0; len < 5; ++len)
      expect(ls_accept(shortbuf, len) == 0, "buffers under 5 bytes rejected");

    // The window wraps: start 0 and start == len visit the same cells.
    std::vector<uint8_t> a = {0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70};
    expect(ls_window(a.data(), a.size(), 0) ==
               ls_window(a.data(), a.size(), (uint32_t)a.size()),
           "window start wraps modulo length");

    // Every byte contributes to the mix.
    std::vector<uint8_t> b = a;
    b.push_back(0x81);
    expect(ls_mix(a.data(), a.size()) != ls_mix(b.data(), b.size()),
           "mix changes when a byte is appended");

    // Long buffers stay in range and stay deterministic.
    std::vector<uint8_t> big(4096, 0x5A);
    expect(ls_window(big.data(), big.size(), 4095) ==
               ls_window(big.data(), big.size(), 4095),
           "window is deterministic");

    if (g_failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n", g_failures);
  }
};

static PropertyChecks g_propertyChecks;
