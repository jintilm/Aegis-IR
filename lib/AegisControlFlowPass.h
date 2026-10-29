//===- AegisControlFlowPass.h ---------------------------------------------===//
//
// Level 2/3 control-flow transforms:
//   * level 2: an input-driven live split plus opaque-predicate bogus edges
//     (every inserted edge is dynamically dead: the predicate reads a second
//     never-written zero global through a volatile load);
//   * level 3: level 2 plus control-flow flattening into a volatile state
//     machine, so the executed path no longer resembles the source CFG.
//
// Both levels are semantics-preserving by construction; neither implements
// the threat model's Tier-3 "semantics removal" step (cloud/TEE), which is an
// architectural migration and out of scope for this plugin.
//
//===----------------------------------------------------------------------===//

#ifndef AEGIS_AEGIS_CONTROL_FLOW_PASS_H
#define AEGIS_AEGIS_CONTROL_FLOW_PASS_H

#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"

namespace aegis {

class AegisControlFlowPass : public llvm::PassInfoMixin<AegisControlFlowPass> {
public:
  llvm::PreservedAnalyses run(llvm::Module &M, llvm::ModuleAnalysisManager &);
};

} // namespace aegis

#endif // AEGIS_AEGIS_CONTROL_FLOW_PASS_H
