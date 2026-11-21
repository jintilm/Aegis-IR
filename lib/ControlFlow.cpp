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

std::string flatteningIneligibilityReason(const Function &F) {
  StringRef Base = ineligibilityReason(F);
  if (!Base.empty())
    return Base.str();

  // A longjmp/setjmp pair creates a second entry point into the body; the
  // dispatcher would only be initialised on the normal path.
  if (F.callsFunctionThatReturnsTwice())
    return "calls a returns_twice function (setjmp/longjmp)";

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

  // Only fixed-size entry allocas can be moved to the dispatcher prologue.
  // A VLA/non-entry allocation may depend on values and stack lifetimes in
  // its original block; flattening would break dominance or allocation count.
  for (const Instruction &I : instructions(F))
    if (const auto *AI = dyn_cast<AllocaInst>(&I))
      if (!AI->isStaticAlloca())
        return "dynamic or non-entry alloca (VLA/stack lifetime cannot be "
               "flattened safely)";

  // Intrinsics whose lowering depends on the surrounding CFG shape or that
  // carry runtime state the rewrite cannot preserve.
  static constexpr StringLiteral kRejectedPrefixes[] = {
      "llvm.coro.",
      "llvm.experimental.gc.",
      "llvm.call.preallocated.",
      "llvm.experimental.stackmap",
      "llvm.experimental.patchpoint",
      "llvm.experimental.deoptimize",
  };
  for (const Instruction &I : instructions(F)) {
    const auto *CB = dyn_cast<CallBase>(&I);
    if (!CB)
      continue;
    if (CB->isInlineAsm())
      return "inline assembly (CFG-sensitive, cannot verify the rewrite)";
    const Function *Callee = CB->getCalledFunction();
    if (!Callee)
      continue;
    if (Callee->getName().starts_with("llvm.stacksave") ||
        Callee->getName().starts_with("llvm.stackrestore"))
      return "stack save/restore (dispatcher stack lifetime cannot be "
             "preserved)";
    for (StringLiteral Prefix : kRejectedPrefixes)
      if (Callee->getName().starts_with(Prefix))
        return ("uses " + Prefix + "* intrinsics").str();
    // A convergent call may not be duplicated or moved across a dispatcher.
    if (Callee->isConvergent())
      return "calls a convergent function";
  }
  return {};
}

bool eligibleForFlattening(const Function &F) {
  return flatteningIneligibilityReason(F).empty();
}

} // namespace aegis
