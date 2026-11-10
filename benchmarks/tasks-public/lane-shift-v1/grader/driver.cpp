// Grader driver for lane-shift-v1. Never shipped to the agent workspace.

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
  const uint32_t start = data.empty() ? 0u : data[0];
  std::printf("mix=%u window=%u accept=%d\n",
              ls_mix(ptr, data.size()),
              ls_window(ptr, data.size(), start),
              ls_accept(ptr, data.size()) ? 1 : 0);
  return 0;
}
