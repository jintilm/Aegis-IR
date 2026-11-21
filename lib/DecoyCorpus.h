//===- DecoyCorpus.h - deterministic decoy plan shared by passes ----------===//
//
// The decoy transform and the verifier must agree, byte for byte, on which
// decoy artifacts a module should contain. This header exposes that shared
// deterministic plan plus small helpers for reading the policy markers that
// `aegis-policy` wrote.
//
// The plan depends only on the module seed (`aegis.seed` module flag), never
// on paths or timestamps, so builds are reproducible across machines.
//
//===----------------------------------------------------------------------===//

#ifndef AEGIS_DECOY_CORPUS_H
#define AEGIS_DECOY_CORPUS_H

#include "llvm/IR/Function.h"
#include "llvm/IR/Module.h"

#include <cstdint>
#include <string>
#include <vector>

namespace aegis {

/// The guard global that decoy branches test. It is internal, zero
/// initialised, and never stored to; the verifier enforces the "never stored"
/// property, which is what makes decoy branches dynamically unreachable.
extern const char *const kGuardGlobalName;

/// Module flag recording which functions the transform actually guarded, as an
/// MDNode of MDString operands. The verifier needs this because a function that
/// the optimizer inlined away takes its `aegis.level` attribute with it — the
/// attribute alone cannot distinguish "not selected" from "selected, then
/// erased".
extern const char *const kGuardedFlagName;

/// Durable policy intent, retained even if optimization removes every selected
/// function before the decoy pass runs. Its presence prevents verification from
/// mistaking a lost protected body for a deliberately unprotected module.
extern const char *const kProtectionRequestedFlagName;

/// Record positive protection intent once, including attribute-only pipelines.
void recordProtectionRequest(llvm::Module &M);

/// Highest policy level any shipped transform implements. A policy entry above
/// this must fail the build: accepting it would ship a module that claims a
/// protection tier nothing applied.
constexpr int kMaxImplementedLevel = 3;

/// Deterministic description of the decoys a module must contain.
struct DecoyPlan {
  uint32_t Seed = 0;
  std::vector<std::string> FunctionNames; // plausible symbol names
  std::vector<std::string> Strings;       // plausible decoy strings
};

/// Build the plan for a seed. Pure function: same seed, same plan.
DecoyPlan buildDecoyPlan(uint32_t Seed);

/// Read the `aegis.seed` module flag; 0 if absent.
uint32_t moduleSeed(const llvm::Module &M);

/// Read the `aegis.level` function attribute; -1 if absent or malformed.
int functionLevel(const llvm::Function &F);

/// True when the function is a definition the transform is allowed to touch.
/// The verifier applies the same predicate so both agree on which functions
/// must carry a decoy branch.
bool eligibleForDecoys(const llvm::Function &F);

/// Why the transform cannot protect this function ("" when it can). Used to
/// turn "policy asked for this, nothing applied" into a build error that names
/// the reason instead of a silent no-op.
llvm::StringRef ineligibilityReason(const llvm::Function &F);

} // namespace aegis

#endif // AEGIS_DECOY_CORPUS_H
