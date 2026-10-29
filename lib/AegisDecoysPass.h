//===- AegisDecoysPass.h --------------------------------------------------===//

#ifndef AEGIS_AEGIS_DECOYS_PASS_H
#define AEGIS_AEGIS_DECOYS_PASS_H

#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

namespace aegis {

/// Tier-1 decoy injection. Emits plausible external decoy functions with
/// curated strings, then guards every policy-selected function with a branch
/// that is dynamically dead by construction (volatile read of a never-written
/// zero global). Registered as `aegis-decoys`; semantics-preserving.
class AegisDecoysPass : public llvm::PassInfoMixin<AegisDecoysPass> {
public:
  llvm::PreservedAnalyses run(llvm::Module &M, llvm::ModuleAnalysisManager &);
};

} // namespace aegis

#endif // AEGIS_AEGIS_DECOYS_PASS_H