//===- AegisLintPass.cpp - pre-transform protectability report -----------===//
//
// This pass is deliberately read-only. It exists so a policy can be checked
// before a transform pipeline spends build time, and so an ineligible function
// is visible during policy review rather than only when aegis-decoys or
// aegis-cff fails the build.
//
//===----------------------------------------------------------------------===//

#include "AegisLintPass.h"
#include "ControlFlow.h"
#include "DecoyCorpus.h"

#include "llvm/IR/Function.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace aegis {

namespace {

bool isSmallStatelessCandidate(const Function &F) {
  // Deliberately conservative: a function is only a migration candidate when
  // its complete behaviour is visible in a small, memory-free body. Calls,
  // allocas, global references and any other memory access keep the default
  // protect-and-measure recommendation.
  if (F.getInstructionCount() == 0 || F.getInstructionCount() > 32 ||
      F.size() > 5)
    return false;

  for (const Instruction &I : instructions(F)) {
    if (isa<AllocaInst>(I) || isa<CallBase>(I))
      return false;
    if (I.mayReadOrWriteMemory())
      return false;
    for (const Use &Operand : I.operands())
      if (isa<GlobalVariable>(Operand->stripPointerCasts()))
        return false;
  }
  return true;
}

StringRef repairAdvice(StringRef Reason) {
  if (Reason.contains("indirectbr"))
    return "rewrite-computed-goto-or-select-another-function";
  if (Reason.contains("callbr"))
    return "replace-callbr-or-select-another-function";
  if (Reason.contains("exception-handling"))
    return "move-exception-path-out-of-selected-function";
  if (Reason.contains("returns_twice"))
    return "isolate-setjmp-longjmp-from-selected-function";
  if (Reason.contains("inline assembly"))
    return "replace-inline-assembly-or-select-another-function";
  if (Reason.contains("coro."))
    return "exclude-coroutine-function-from-flattening";
  if (Reason.contains("convergent"))
    return "do-not-flatten-convergent-callers";
  if (Reason.contains("optnone"))
    return "recompile-with-optimization-or-select-another-function";
  if (Reason.contains("musttail"))
    return "remove-musttail-or-select-another-function";
  if (Reason.contains("available_externally"))
    return "select-a-defined-function-with-local-linkage";
  if (Reason.contains("personality"))
    return "exclude-eh-personality-function";
  if (Reason.contains("naked"))
    return "exclude-naked-function";
  return "refine-policy-or-select-another-function";
}

} // namespace

PreservedAnalyses AegisLintPass::run(Module &M, ModuleAnalysisManager &) {
  unsigned Functions = 0;
  unsigned Selected = 0;
  unsigned Eligible = 0;
  unsigned Ineligible = 0;
  unsigned Unsupported = 0;
  unsigned ProtectAndMeasure = 0;
  unsigned MoveToServer = 0;
  unsigned RepairSelections = 0;

  errs() << "[aegis-lint] module: " << M.getSourceFileName() << " ("
         << M.getName() << ")\n";
  for (Function &F : M) {
    if (F.isDeclaration())
      continue;
    ++Functions;

    const int Level = functionLevel(F);
    if (Level < 1) {
      errs() << "[aegis-lint] function=" << F.getName() << " level=" << Level
             << " selected=no blocks=" << F.size()
             << " instructions=" << F.getInstructionCount() << "\n";
      continue;
    }
    ++Selected;

    if (Level > kMaxImplementedLevel) {
      ++Unsupported;
      ++RepairSelections;
      errs() << "[aegis-lint] function=" << F.getName() << " level=" << Level
             << " eligible=no reason=level above implemented maximum"
             << " advisory=lower-level-or-fix-selection\n";
      continue;
    }

    const StringRef Reason =
        Level >= 3 ? flatteningIneligibilityReason(F) : ineligibilityReason(F);
    errs() << "[aegis-lint] function=" << F.getName() << " level=" << Level;
    if (Reason.empty()) {
      ++Eligible;
      errs() << " eligible=yes";
      if (isSmallStatelessCandidate(F)) {
        ++MoveToServer;
        errs() << " advisory=move-to-server";
      } else {
        ++ProtectAndMeasure;
        errs() << " advisory=protect-and-measure";
      }
    } else {
      ++Ineligible;
      ++RepairSelections;
      errs() << " eligible=no reason=" << Reason
             << " advisory=" << repairAdvice(Reason);
    }
    errs() << " blocks=" << F.size()
           << " instructions=" << F.getInstructionCount() << "\n";
  }

  errs() << "[aegis-lint] summary: functions=" << Functions
         << " selected=" << Selected << " eligible=" << Eligible
         << " ineligible=" << Ineligible << " unsupported=" << Unsupported
         << " protect_and_measure=" << ProtectAndMeasure
         << " move_to_server=" << MoveToServer
         << " repair_selections=" << RepairSelections << "\n";
  return PreservedAnalyses::all();
}

} // namespace aegis
