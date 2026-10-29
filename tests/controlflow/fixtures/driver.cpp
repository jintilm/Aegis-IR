// Unprotected driver for the control-flow transform fixture. Prints one
// deterministic summary line; run.sh compares it against every protected
// build.

#include <cstddef>
#include <cstdint>
#include <cstdio>

extern uint32_t branchy(uint32_t x);
extern uint64_t loop_sum(const uint8_t *data, size_t len);
extern uint32_t switchy(uint32_t x);
extern int early(const uint8_t *data, size_t len);
extern uint32_t no_args();
extern uint32_t pointer_only(const uint8_t *data);

int main() {
  uint8_t buf[300];
  for (size_t i = 0; i < sizeof(buf); ++i)
    buf[i] = static_cast<uint8_t>((i * 37 + 11) & 0xFF);
  buf[17] = 0;
  buf[255] = 0xFF;

  uint64_t acc = 0;
  for (uint32_t i = 0; i < 64; ++i)
    acc = acc * 1315423911u + branchy(i);
  for (uint32_t i = 0; i < 16; ++i)
    acc = acc * 1315423911u + switchy(i);
  const size_t lengths[] = {0, 1, 2, 7, 18, 64, 300};
  for (size_t len : lengths) {
    acc += loop_sum(buf, len);
    acc += static_cast<uint64_t>(static_cast<int64_t>(early(buf, len)));
  }
  acc += no_args();
  acc += pointer_only(buf);
  acc += pointer_only(nullptr);

  std::printf("%llu\n", static_cast<unsigned long long>(acc));
  return 0;
}
