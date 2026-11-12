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
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace aegis {

PreservedAnalyses AegisLintPass::run(Module &M, ModuleAnalysisManager &) {
  unsigned Functions = 0;
  unsigned Selected = 0;
  unsigned Eligible = 0;
  unsigned Ineligible = 0;
  unsigned Unsupported = 0;

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
      errs() << "[aegis-lint] function=" << F.getName() << " level=" << Level
             << " eligible=no reason=level above implemented maximum\n";
      continue;
    }

    const StringRef Reason =
        Level >= 3 ? flatteningIneligibilityReason(F) : ineligibilityReason(F);
    errs() << "[aegis-lint] function=" << F.getName() << " level=" << Level;
    if (Reason.empty()) {
      ++Eligible;
      errs() << " eligible=yes";
    } else {
      ++Ineligible;
      errs() << " eligible=no reason=" << Reason;
    }
    errs() << " blocks=" << F.size()
           << " instructions=" << F.getInstructionCount() << "\n";
  }

  errs() << "[aegis-lint] summary: functions=" << Functions
         << " selected=" << Selected << " eligible=" << Eligible
         << " ineligible=" << Ineligible << " unsupported=" << Unsupported
         << "\n";
  return PreservedAnalyses::all();
}

} // namespace aegis
