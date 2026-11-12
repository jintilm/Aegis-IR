#include "target.h"

#include <cstring>

namespace {
constexpr int kSize = 8;
constexpr int kCells = kSize * kSize;

int cell_index(int row, int col) {
  return row * kSize + col;
}
} // namespace

uint32_t gr_route(const uint8_t *data, size_t len) {
  bool blocked[kCells] = {};
  uint32_t blocked_count = 0;
  for (int index = 0; index < kCells; ++index) {
    uint8_t byte = 0;
    if (len) {
      const size_t offset =
          (static_cast<size_t>(index) * 13u + len * 3u) % len;
      byte = data[offset];
    }
    const bool pattern =
        ((byte >> ((index + len) & 7u)) & 1u) != 0;
    const bool dark = ((index * 3u + len) % 5u) == 0;
    blocked[index] = (pattern ^ dark);
    if (blocked[index])
      ++blocked_count;
  }
  blocked[0] = false;
  blocked[kCells - 1] = false;

  int distance[kCells];
  for (int i = 0; i < kCells; ++i)
    distance[i] = -1;
  int queue[kCells];
  int head = 0;
  int tail = 0;
  queue[tail++] = 0;
  distance[0] = 0;
  const int dr[4] = {-1, 1, 0, 0};
  const int dc[4] = {0, 0, -1, 1};
  while (head < tail) {
    const int index = queue[head++];
    const int row = index / kSize;
    const int col = index % kSize;
    for (int k = 0; k < 4; ++k) {
      const int nr = row + dr[k];
      const int nc = col + dc[k];
      if (nr < 0 || nr >= kSize || nc < 0 || nc >= kSize)
        continue;
      const int n = cell_index(nr, nc);
      if (blocked[n] || distance[n] >= 0)
        continue;
      distance[n] = distance[index] + 1;
      queue[tail++] = n;
    }
  }
  uint32_t reachable = 0;
  for (int i = 0; i < kCells; ++i)
    if (distance[i] >= 0)
      ++reachable;
  const uint32_t path = distance[kCells - 1] < 0
                            ? 0xFFu
                            : static_cast<uint32_t>(distance[kCells - 1]);
  return (path << 24) ^ (reachable * 0x9E3779B1u) ^
         (blocked_count * 0x85EBCA6Bu) ^
         (static_cast<uint32_t>(len) * 0x27D4EB2Fu);
}

int gr_accept(const uint8_t *data, size_t len) {
  if (len < 8)
    return 0;
  return (gr_route(data, len) & 7u) ==
                 ((static_cast<uint32_t>(data[0]) ^
                   static_cast<uint32_t>(data[len - 1])) &
                  7u)
             ? 1
             : 0;
}
