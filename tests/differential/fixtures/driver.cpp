// Driver for the differential harness. Reads all of stdin, calls the fixture
// library, prints a deterministic summary line, and runs property checks
// against the library contract. Exit code 3 marks a property violation.

#include "algorithm_lib.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

namespace {
int g_propertyFailures = 0;

void expect(bool condition, const char *what) {
  if (!condition) {
    std::fprintf(stderr, "PROPERTY FAIL: %s\n", what);
    ++g_propertyFailures;
  }
}
} // namespace

int main() {
  std::vector<uint8_t> data;
  uint8_t buf[4096];
  size_t n;
  while ((n = std::fread(buf, 1, sizeof(buf), stdin)) > 0)
    data.insert(data.end(), buf, buf + n);

  // Contract properties, checked on every run.
  expect(rolling_hash(nullptr, 0) == 1469598103934665603ULL,
         "fnv offset basis");
  expect(checksum32(nullptr, 0) == 1, "adler init");
  expect(rolling_hash(data.data(), data.size()) ==
             rolling_hash(data.data(), data.size()),
         "hash deterministic");
  expect(!verify_token(data.data(), 0), "empty token rejected");
  expect(!verify_token(data.data(), 7), "short token rejected");

  const uint64_t hash = rolling_hash(data.data(), data.size());
  const uint32_t check = checksum32(data.data(), data.size());
  const bool token = verify_token(data.data(), data.size());

  std::printf("len=%zu hash=%llu checksum=%u token=%d\n", data.size(),
              static_cast<unsigned long long>(hash), check, token ? 1 : 0);

  if (g_propertyFailures > 0) {
    std::fprintf(stderr, "%d property failure(s)\n", g_propertyFailures);
    return 3;
  }
  return 0;
}