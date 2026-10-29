// Independent property tests for rolling-token-v1. Never shipped to the agent
// workspace. These check structural facts a correct implementation must have,
// independent of the differential comparison; they are the reason a candidate
// cannot pass by hard-coding the visible examples.
//
// Failures go to stderr so they never perturb the stdout comparison; the
// grader scans stderr for "PROPERTY FAIL".

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

// Runs before main(): the driver owns main().
struct PropertyChecks {
  PropertyChecks() {
    // FNV offset basis / Adler seed on empty input.
    expect(bench_hash(nullptr, 0) == 14695981039346656037ULL,
           "hash of empty input is the FNV offset basis");
    expect(bench_checksum(nullptr, 0) == 1, "checksum of empty input is 1");
    expect(bench_verify(nullptr, 0) == 0, "empty buffer is not a valid token");

    // Short buffers are never valid tokens.
    const uint8_t shortbuf[7] = {1, 2, 3, 4, 5, 6, 7};
    for (size_t len = 1; len < 8; ++len)
      expect(bench_verify(shortbuf, len) == 0,
             "buffers shorter than 8 bytes are rejected");

    // No dependence on bytes past len.
    std::vector<uint8_t> a(64, 0x5A);
    std::vector<uint8_t> b = a;
    b.resize(128, 0xFF);
    expect(bench_hash(a.data(), a.size()) == bench_hash(b.data(), a.size()),
           "hash ignores bytes past len");
    expect(bench_checksum(a.data(), a.size()) ==
               bench_checksum(b.data(), a.size()),
           "checksum ignores bytes past len");

    // A single appended byte must change the hash.
    std::vector<uint8_t> c(31, 0x00);
    const uint64_t h1 = bench_hash(c.data(), c.size());
    c.push_back(0x01);
    expect(bench_hash(c.data(), c.size()) != h1,
           "appending a byte changes the hash");

    // Adler-32 bounds: both halves are reduced modulo 65521.
    const uint32_t sum = bench_checksum(a.data(), a.size());
    expect((sum >> 16) < 65521 && (sum & 0xFFFF) < 65521,
           "adler halves are reduced modulo 65521");

    if (g_failures)
      std::fprintf(stderr, "PROPERTY FAIL: %d failure(s) total\n", g_failures);
  }
};

static PropertyChecks g_propertyChecks;
