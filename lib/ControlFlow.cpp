//===- ControlFlow.cpp - shared state for the level 2/3 CF transforms -----===//

#include "ControlFlow.h"

#include "DecoyCorpus.h"

#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"

using namespace llvm;

namespace aegis {

const char *const kCffSaltName = "__aegis.cff.salt";
const char *const kBogusFlagName = "aegis.cff.bogus";
const char *const kFlattenedFlagName = "aegis.cff.flattened";

namespace {

uint64_t splitmix64(uint64_t X) {
  X += 0x9E3779B97F4A7C15ULL;
  X = (X ^ (X >> 30)) * 0xBF58476D1CE4E5B9ULL;
  X = (X ^ (X >> 27)) * 0x94D049BB133111EBULL;
  return X ^ (X >> 31);
}

} // namespace

uint32_t controlFlowKey(uint32_t Seed) {
  uint32_t Key = static_cast<uint32_t>(splitmix64(Seed ^ 0xCFF1A7E5ULL));
  // A zero key would leave state indices readable as themselves; avoid it.
  return Key == 0 ? 0xA5A5A5A5u : Key;
}

StringRef flatteningIneligibilityReason(const Function &F) {
  StringRef Base = ineligibilityReason(F);
  if (!Base.empty())
    return Base;

  for (const BasicBlock &BB : F) {
    const Instruction *T = BB.getTerminator();
    if (isa<IndirectBrInst>(T))
      return "indirectbr (computed goto cannot be flattened safely)";
    if (isa<CallBrInst>(T))
      return "callbr";
    if (isa<InvokeInst>(T) || isa<CatchSwitchInst>(T) ||
        isa<CatchReturnInst>(T) || isa<CleanupReturnInst>(T) ||
        isa<ResumeInst>(T))
      return "exception-handling terminator";
  }

  for (const Instruction &I : instructions(F)) {
    const auto *CB = dyn_cast<CallBase>(&I);
    if (!CB)
      continue;
    const Function *Callee = CB->getCalledFunction();
    if (!Callee)
      continue;
    if (Callee->getName().starts_with("llvm.coro."))
      return "coroutine (llvm.coro.* intrinsics)";
  }
  return StringRef();
}

bool eligibleForFlattening(const Function &F) {
  return flatteningIneligibilityReason(F).empty();
}

} // namespace aegis
