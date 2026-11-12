#pragma once

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

uint32_t bm_mosaic(const uint8_t *data, size_t len);
int bm_accept(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
