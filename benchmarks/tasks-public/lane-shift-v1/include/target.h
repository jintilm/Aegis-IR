#pragma once

#include <cstddef>
#include <cstdint>

// Recover these three functions from the protected library. All three are
// pure functions of their arguments.

#ifdef __cplusplus
extern "C" {
#endif

// Full-buffer mixer.
uint32_t ls_mix(const uint8_t *data, size_t len);

// Rotation over a wrapping five-byte window starting at `start` (reduced
// modulo the buffer length). Returns 0 for an empty buffer.
uint32_t ls_window(const uint8_t *data, size_t len, uint32_t start);

// Returns 1 when the buffer is accepted, 0 otherwise.
int ls_accept(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
