#include "target.h"

#include <cstdio>
#include <vector>

int main() {
  std::vector<uint8_t> data;
  uint8_t buf[4096];
  size_t n;
  while ((n = std::fread(buf, 1, sizeof(buf), stdin)) > 0)
    data.insert(data.end(), buf, buf + n);
  const uint8_t *ptr = data.empty() ? nullptr : data.data();
  const uint32_t cap = data.empty() ? 1u : 1u + (data[0] & 63u);
  std::printf("ring=%u accept=%d\n", rd_ring(ptr, data.size(), cap),
              rd_accept(ptr, data.size()) ? 1 : 0);
  return 0;
}
