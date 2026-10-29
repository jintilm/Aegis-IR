//===- AegisVerifyPass.h --------------------------------------------------===//

#ifndef AEGIS_AEGIS_VERIFY_PASS_H
#define AEGIS_AEGIS_VERIFY_PASS_H

#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

namespace aegis {

/// Post-optimization gate for the decoy layer. Recomputes the expected decoy
/// plan from the module seed and fails the build when any artifact was lost:
/// missing decoy functions/strings, a writable guard global, or a selected
/// function whose decoy branch did not survive optimization. Registered as
/// `aegis-verify`; must run after the optimization pipeline.
class AegisVerifyPass : public llvm::PassInfoMixin<AegisVerifyPass> {
public:
  llvm::PreservedAnalyses run(llvm::Module &M, llvm::ModuleAnalysisManager &);
};

} // namespace aegis

#endif // AEGIS_AEGIS_VERIFY_PASS_H