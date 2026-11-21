// Valid C11 VLA: its allocation is inside the guarded range, not the entry.
int vla_target(int n, int choose) {
  if (n < 1 || n > 16)
    return 0;
  int values[n];
  if (choose)
    values[0] = 42;
  else
    values[0] = 24;
  return values[0];
}

int main(void) {
  return vla_target(4, 1) != 42 || vla_target(4, 0) != 24 ||
         vla_target(0, 1) != 0 || vla_target(17, 0) != 0;
}
