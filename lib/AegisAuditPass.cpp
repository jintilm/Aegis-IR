//===- AegisAuditPass.cpp - read-only module audit pass -------------------===//
//
// The first pass in the project. It does not modify the module; it reports
// per-function size statistics so we can verify the plugin registration,
// loading and analysis pipeline end to end before any transform exists.
//
//===----------------------------------------------------------------------===//

#include "AegisAuditPass.h"
#include "aegis/AegisVersion.h"

#include "llvm/IR/Function.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace aegis {

PreservedAnalyses AegisAuditPass::run(Module &M, ModuleAnalysisManager &) {
  uint64_t TotalFunctions = 0;
  uint64_t TotalBlocks = 0;
  uint64_t TotalInstructions = 0;

  errs() << "[aegis-audit] module: " << M.getSourceFileName() << " ("
         << M.getName() << ")\n";

  for (Function &F : M) {
    if (F.isDeclaration())
      continue;

    size_t Blocks = 0;
    size_t Instructions = 0;
    for (BasicBlock &BB : F) {
      ++Blocks;
      Instructions += BB.size();
    }

    errs() << "[aegis-audit]   function=" << F.getName() << " blocks=" << Blocks
           << " instructions=" << Instructions << "\n";

    ++TotalFunctions;
    TotalBlocks += Blocks;
    TotalInstructions += Instructions;
  }

  errs() << "[aegis-audit] total: functions=" << TotalFunctions
         << " blocks=" << TotalBlocks << " instructions=" << TotalInstructions
         << "\n";

  // Read-only pass: all analyses remain valid.
  return PreservedAnalyses::all();
}

} // namespace aegis