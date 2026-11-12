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
    expect(wp_parse(nullptr, 0) == 0xA5F1C39Bu,
           "empty parse returns the seed");
    expect(wp_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t shortbuf[5] = {0, 1, 2, 3, 4};
    for (size_t len = 0; len < 6; ++len)
      expect(wp_accept(shortbuf, len) == 0,
             "buffers shorter than six bytes are rejected");

    std::vector<uint8_t> a = {0x21, 0x62, 0x43, 0xE0, 0xAA, 0x55,
                              0x11, 0x22};
    expect(wp_parse(a.data(), a.size()) ==
               wp_parse(a.data(), a.size()),
           "parse is deterministic");
    std::vector<uint8_t> b = a;
    std::swap(b[0], b[1]);
    expect(wp_parse(a.data(), a.size()) != wp_parse(b.data(), b.size()),
           "parse changes when the first bytes reorder");

    std::vector<uint8_t> truncated = {0x7F, 0x7F, 0x7F};
    expect(wp_parse(truncated.data(), truncated.size()) ==
               wp_parse(truncated.data(), truncated.size()),
           "truncated payloads remain deterministic");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
