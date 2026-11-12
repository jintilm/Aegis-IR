#include "target.h"

#include <cstdio>
#include <vector>

namespace {
int failures = 0;
void expect(bool cond, const char *message) {
  if (!cond) {
    std::fprintf(stderr, "PROPERTY FAIL: %s\n", message);
    ++failures;
  }
}
} // namespace

struct PropertyChecks {
  PropertyChecks() {
    expect(rd_ring(nullptr, 0, 8) == 0x811C9DC5u,
           "empty ring returns the seed");
    expect(rd_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t shortbuf[7] = {0, 1, 2, 3, 4, 5, 6};
    for (size_t len = 0; len < 8; ++len)
      expect(rd_accept(shortbuf, len) == 0,
             "buffers shorter than eight bytes are rejected");

    std::vector<uint8_t> a = {0x01, 0x02, 0x03, 0x42, 0x81, 0xC1,
                              0x05, 0x06};
    expect(rd_ring(a.data(), a.size(), 4) ==
               rd_ring(a.data(), a.size(), 4),
           "ring is deterministic");
    std::vector<uint8_t> b = a;
    std::swap(b[0], b[2]);
    expect(rd_ring(a.data(), a.size(), 4) !=
               rd_ring(b.data(), b.size(), 4),
           "ring is command-order-sensitive");

    std::vector<uint8_t> reset = a;
    reset.push_back(0x80);
    expect(rd_ring(reset.data(), reset.size(), 4) !=
               rd_ring(a.data(), a.size(), 4),
           "reset changes the resulting state");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
