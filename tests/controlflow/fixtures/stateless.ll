; Minimal memory-free function used to exercise deterministic migration advice.
define i32 @tiny_pure(i32 %x) {
entry:
  %mixed = mul i32 %x, 17
  %biased = add i32 %mixed, 23
  %masked = and i32 %biased, 1023
  ret i32 %masked
}
