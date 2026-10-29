// Control-flow transform fixture: branches, loops, early returns, a switch,
// pointer-only and argument-free functions. The driver prints a summary; the
// differential comparison in run.sh catches any semantic drift introduced by
// level 2/3.

#include <cstddef>
#include <cstdint>

uint32_t branchy(uint32_t x) {
  if (x % 3 == 0)
    return x * 7 + 1;
  if (x % 5 == 0)
    return x ^ 0x5A5A5A5Au;
  if (x & 1)
    return x >> 1;
  return x + 0x12345678u;
}

uint64_t loop_sum(const uint8_t *data, size_t len) {
  uint64_t acc = 0;
  for (size_t i = 0; i < len; ++i) {
    acc += data[i];
    if (data[i] == 0)
      break;
    acc ^= acc >> 7;
  }
  return acc;
}

uint32_t switchy(uint32_t x) {
  switch (x & 7) {
  case 0:
    return 11;
  case 1:
    return 23;
  case 2:
    return 37;
  case 3:
    return 53;
  case 4:
    return 71;
  case 5:
    return 97;
  case 6:
    return 113;
  default:
    return 131;
  }
}

int early(const uint8_t *data, size_t len) {
  if (len < 2)
    return -1;
  if (data[0] == 0xFF)
    return -2;
  int v = 0;
  for (size_t i = 0; i < len; ++i) {
    if (data[i] == 0)
      return v;
    v = (v * 33 + data[i]) % 100000;
  }
  return v;
}

uint32_t no_args() { return 0xC0FFEEu; }

uint32_t pointer_only(const uint8_t *data) {
  return data ? static_cast<uint32_t>(data[0]) * 3 + 1 : 7;
}

// Selected only by the ineligible policy: computed goto lowers to
// `indirectbr`, which level 3 must reject rather than mishandle.
__attribute__((noinline)) int computed_goto(int x) {
  static void *const kTargets[] = {&&zero, &&one};
  goto *kTargets[x & 1];
zero:
  return 10;
one:
  return 20;
}
