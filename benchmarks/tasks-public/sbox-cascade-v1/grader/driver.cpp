#include "target.h"

#include <cstdio>
#include <vector>

int main() {
  std::vector<uint8_t> data;
  uint8_t buffer[4096];
  size_t count;
  while ((count = std::fread(buffer, 1, sizeof(buffer), stdin)) > 0)
    data.insert(data.end(), buffer, buffer + count);
  const uint8_t *ptr = data.empty() ? nullptr : data.data();
  std::printf("scrub=%u accept=%d\n", sc_scrub(ptr, data.size()),
              sc_accept(ptr, data.size()) ? 1 : 0);
  return 0;
}
