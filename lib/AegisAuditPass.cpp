//===- AegisAuditPass.cpp - read-only module audit pass -------------------===//
//
// The first pass in the project. It does not modify the module; it reports
// per-function size statistics so we can verify the plugin registration,
// loading and analysis pipeline end to end before any transform exists.
//
//===----------------------------------------------------------------------===//

#include "aegis/AegisVersion.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
// LLVM 20+ moved PassPlugin.h from llvm/Passes/ to llvm/Plugins/.
#if __has_include("llvm/Plugins/PassPlugin.h")
#include "llvm/Plugins/PassPlugin.h"
#else
#include "llvm/Passes/PassPlugin.h"
#endif
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace {

class AegisAuditPass : public PassInfoMixin<AegisAuditPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
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

      errs() << "[aegis-audit]   function=" << F.getName()
             << " blocks=" << Blocks << " instructions=" << Instructions
             << "\n";

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
};

} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "AegisPass", AEGIS_VERSION_STRING,
          [](PassBuilder &PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager &MPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name != "aegis-audit")
                    return false;
                  MPM.addPass(AegisAuditPass());
                  return true;
                });
          }};
}