#pragma once

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

uint32_t dl_score(const uint8_t *data, size_t len);
int dl_accept(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
