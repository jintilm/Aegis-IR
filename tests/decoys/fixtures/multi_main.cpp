extern "C" unsigned protected_one(unsigned);
extern "C" unsigned protected_two(unsigned);

int main() {
  for (unsigned value = 0; value < 100; ++value) {
    const unsigned expected = value * 3u + 7u;
    if (protected_one(value) != expected || protected_two(value) != expected)
      return 1;
  }
  return 0;
}
