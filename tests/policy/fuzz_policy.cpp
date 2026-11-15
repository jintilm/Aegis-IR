#include "aegis/Policy.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstddef>
#include <cstdint>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {
  if (Size > (1U << 20))
    return 0;
  llvm::StringRef Input(reinterpret_cast<const char *>(Data), Size);
  auto Policy = aegis::parsePolicy(Input, "<fuzz-policy>");
  if (!Policy)
    llvm::consumeError(Policy.takeError());
  return 0;
}
