#ifndef AEGIS_REPRESENTATIVE_ALGORITHM_LIB_H
#define AEGIS_REPRESENTATIVE_ALGORITHM_LIB_H

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

// Parses byte-oriented records into fixed-width numeric fields.
std::size_t aegis_rep_parse(const std::uint8_t *data, std::size_t len,
                            std::uint32_t *records, std::size_t capacity);

// Folds parsed records into a compact checksum state.
std::uint64_t aegis_rep_fold(const std::uint32_t *records, std::size_t count);

// Runs multiple state-update rounds over the parsed record set.
std::uint64_t aegis_rep_rounds(std::uint64_t seed, const std::uint32_t *records,
                               std::size_t count);

// Final digest over both the records and the loop result.
std::uint32_t aegis_rep_digest(const std::uint32_t *records, std::size_t count,
                               std::uint64_t folded);

#ifdef __cplusplus
}
#endif

#endif // AEGIS_REPRESENTATIVE_ALGORITHM_LIB_H
