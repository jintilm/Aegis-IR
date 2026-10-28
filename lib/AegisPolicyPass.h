//===- AegisPolicyPass.h --------------------------------------------------===//

#ifndef AEGIS_AEGIS_POLICY_PASS_H
#define AEGIS_AEGIS_POLICY_PASS_H

#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

#include <string>

namespace aegis {

/// Lowers a policy JSON file to `aegis.level` function attributes and
/// `aegis.profile` / `aegis.seed` module flags. Registered as
/// `aegis-policy<policy=FILE>`; must run first in the pipeline.
class AegisPolicyPass : public llvm::PassInfoMixin<AegisPolicyPass> {
public:
  explicit AegisPolicyPass(std::string PolicyPath);
  llvm::PreservedAnalyses run(llvm::Module &M, llvm::ModuleAnalysisManager &);

private:
  std::string PolicyPath;
};

} // namespace aegis

#endif // AEGIS_AEGIS_POLICY_PASS_H