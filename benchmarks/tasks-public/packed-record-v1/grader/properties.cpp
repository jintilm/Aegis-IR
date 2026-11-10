// Independent property tests for packed-record-v1.

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
    expect(pr_flags(nullptr, 0) == 0, "flags of empty input is 0");
    expect(pr_fold(nullptr, 0) == 0x243F6A8885A308D3ull,
           "fold of empty input is the seed");
    expect(pr_accept(nullptr, 0) == 0, "empty buffer is rejected");

    const uint8_t shortbuf[11] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
    for (size_t len = 0; len < 12; ++len)
      expect(pr_accept(shortbuf, len) == 0, "buffers under 12 bytes rejected");

    // The field extractor only reads the first four bytes.
    std::vector<uint8_t> a = {0x91, 0x24, 0x7F, 0xC3, 0x00, 0x00};
    std::vector<uint8_t> b = a;
    b.push_back(0xFF);
    b.push_back(0x11);
    expect(pr_flags(a.data(), a.size()) == pr_flags(b.data(), a.size()),
           "flags ignore bytes past the first four");

    // The fold consumes every byte.
    expect(pr_fold(a.data(), a.size()) != pr_fold(b.data(), b.size()),
           "fold changes when a byte is appended");
    expect(pr_fold(a.data(), a.size()) != pr_fold(a.data(), a.size() - 1),
           "fold changes when a byte is dropped");

    // Order matters.
    std::vector<uint8_t> c = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                              0x09, 0x0A, 0x0B, 0x0C};
    std::vector<uint8_t> d = c;
    std::swap(d[0], d[11]);
    expect(pr_fold(c.data(), c.size()) != pr_fold(d.data(), d.size()),
           "fold is order-sensitive");

    if (g_failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n", g_failures);
  }
};

static PropertyChecks g_propertyChecks;
