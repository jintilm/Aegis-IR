#pragma once

#include <cstddef>
#include <cstdint>

// Recover these three functions from the protected library.
//
// The interface is deliberately C-like: the task is the algorithm, not the
// symbol mangling. All three are pure functions of (data, len).

#ifdef __cplusplus
extern "C" {
#endif

// Packs the first four bytes (zero-padded when shorter) into a field layout
// whose widths are part of what must be recovered.
uint32_t pr_flags(const uint8_t *data, size_t len);

// Order-sensitive fold over every byte of the buffer.
uint64_t pr_fold(const uint8_t *data, size_t len);

// Returns 1 when the buffer is accepted, 0 otherwise.
int pr_accept(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
