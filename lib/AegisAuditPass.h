//===- AegisAuditPass.h ---------------------------------------------------===//

#ifndef AEGIS_AEGIS_AUDIT_PASS_H
#define AEGIS_AEGIS_AUDIT_PASS_H

#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

namespace aegis {

/// Read-only module audit: prints per-function block/instruction statistics.
/// Registered as `aegis-audit`; exists to prove the plugin pipeline works and
/// to give benchmarks a cheap structural summary of a module.
class AegisAuditPass : public llvm::PassInfoMixin<AegisAuditPass> {
public:
  llvm::PreservedAnalyses run(llvm::Module &M, llvm::ModuleAnalysisManager &);
};

} // namespace aegis

#endif // AEGIS_AEGIS_AUDIT_PASS_H