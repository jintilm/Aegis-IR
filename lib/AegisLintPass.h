//===- AegisLintPass.h - pre-transform protectability report -------------===//

#ifndef AEGIS_AEGIS_LINT_PASS_H
#define AEGIS_AEGIS_LINT_PASS_H

#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

namespace aegis {

/// Read-only selection lint. It applies the same eligibility predicates as the
/// transforms without changing IR, so policy authors can see which selected
/// functions would make a level>=1 build fail closed.
class AegisLintPass : public llvm::PassInfoMixin<AegisLintPass> {
public:
  llvm::PreservedAnalyses run(llvm::Module &M, llvm::ModuleAnalysisManager &);
};

} // namespace aegis

#endif // AEGIS_AEGIS_LINT_PASS_H
