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
    expect(gr_route(nullptr, 0) == gr_route(nullptr, 0),
           "empty route is deterministic");
    expect(gr_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t shortbuf[7] = {0, 1, 2, 3, 4, 5, 6};
    for (size_t len = 0; len < 8; ++len)
      expect(gr_accept(shortbuf, len) == 0,
             "buffers shorter than eight bytes are rejected");

    std::vector<uint8_t> a(8, 0);
    std::vector<uint8_t> b(8, 0xFF);
    expect(gr_route(a.data(), a.size()) != gr_route(b.data(), b.size()),
           "route changes when the grid mask changes");
    expect(gr_route(a.data(), a.size()) ==
               gr_route(a.data(), a.size()),
           "route is deterministic");

    std::vector<uint8_t> c = {0x10, 0x20, 0x40, 0x80, 0x01, 0x02,
                              0x04, 0x08};
    std::vector<uint8_t> d = c;
    std::swap(d[0], d[7]);
    expect(gr_route(c.data(), c.size()) != gr_route(d.data(), d.size()),
           "route is input-order-sensitive");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
