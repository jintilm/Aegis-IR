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
    constexpr uint64_t seed = 0x6A09E667F3BCC909ull;
    expect(sf_step(seed, 0) == sf_step(seed, 0),
           "step is deterministic");
    expect(sf_step(seed, 1) != sf_step(seed, 2),
           "step depends on the token");
    expect(sf_step(seed, 1) != sf_step(seed + 1, 1),
           "step depends on the state");
    expect(sf_digest(nullptr, 0) ==
               static_cast<uint32_t>(seed ^ (seed >> 32)),
           "empty digest is the folded seed");
    expect(sf_accept(nullptr, 0) == 0, "empty input is rejected");

    const uint8_t shortbuf[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    for (size_t len = 0; len < 9; ++len)
      expect(sf_accept(shortbuf, len) == 0,
             "buffers shorter than nine bytes are rejected");

    std::vector<uint8_t> a = {9, 8, 7, 6, 5, 4, 3, 2, 1};
    std::vector<uint8_t> b = a;
    std::swap(b[0], b[8]);
    expect(sf_digest(a.data(), a.size()) != sf_digest(b.data(), b.size()),
           "digest is order-sensitive");
    b = a;
    b.push_back(0xAA);
    expect(sf_digest(a.data(), a.size()) != sf_digest(b.data(), b.size()),
           "digest changes when a byte is appended");

    if (failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n",
                   failures);
  }
};

static PropertyChecks checks;
