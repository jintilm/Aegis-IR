// Self-authored fixture for the decoy transform tests. Two externally visible
// functions: one selected by the policy, one deliberately left at level 0.

#include <cstddef>

extern "C" unsigned checksum(const unsigned char *data, size_t len) {
  unsigned h = 2166136261u;
  for (size_t i = 0; i < len; ++i) {
    h ^= data[i];
    h *= 16777619u;
  }
  return h;
}

extern "C" int classify(int x) {
  if (x < 0)
    return -1;
  if (x == 0)
    return 0;
  return 1;
}
