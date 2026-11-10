// Grader driver for packed-record-v1. Never shipped to the agent workspace.

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
  std::printf("flags=%u fold=%llu accept=%d\n",
              pr_flags(ptr, data.size()),
              static_cast<unsigned long long>(pr_fold(ptr, data.size())),
              pr_accept(ptr, data.size()) ? 1 : 0);
  return 0;
}
