#pragma once

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

uint64_t sf_step(uint64_t state, uint32_t token);
uint32_t sf_digest(const uint8_t *data, size_t len);
int sf_accept(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
