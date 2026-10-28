#include <cstdio>

int transform_value(int x) { return x * 3 + 7; }

int other_helper(int x) { return x ^ 0x5a; }

int main() {
  printf("%d\n", transform_value(5) + other_helper(2));
  return 0;
}