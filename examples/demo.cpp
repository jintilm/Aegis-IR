#include <iostream>

int transform_value(int x) { return (x * 3) + 7; }

int main() {
  std::cout << transform_value(5) << '\n';
  return 0;
}