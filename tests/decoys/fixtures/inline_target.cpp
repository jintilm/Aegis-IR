// Fixture for the inlining interaction: `leaf_check` is small and single-use,
// so -O2 inlines it into `outer_check`. The decoy branch must ride along with
// the inlined body (and the gate must notice if it does not).

#include <cstddef>

extern "C" int leaf_check(const unsigned char *data, size_t len) {
  unsigned h = 0;
  for (size_t i = 0; i < len; ++i)
    h = h * 31u + data[i];
  return static_cast<int>(h & 1u);
}

extern "C" int outer_check(const unsigned char *data, size_t len) {
  return leaf_check(data, len) + static_cast<int>(len);
}
