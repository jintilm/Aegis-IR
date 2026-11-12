#pragma once

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

uint32_t rd_ring(const uint8_t *data, size_t len, uint32_t cap);
int rd_accept(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
