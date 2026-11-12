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
  const uint32_t token = data.empty() ? 0u : data[0];
  std::printf("step=%llu digest=%u accept=%d\n",
              static_cast<unsigned long long>(
                  sf_step(0x6A09E667F3BCC909ull, token)),
              sf_digest(ptr, data.size()),
              sf_accept(ptr, data.size()) ? 1 : 0);
  return 0;
}
