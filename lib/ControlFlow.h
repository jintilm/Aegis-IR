//===- ControlFlow.h - shared state for the level 2/3 CF transforms -------===//
//
// The control-flow transform and the verifier must agree on the artifacts it
// creates. Everything here is derived from the module seed, so the pair stays
// in sync deterministically.
//
// Names and invariants:
//   * @__aegis.cff.salt is a second internal zero global. It is read through
//     volatile loads only; every opaque predicate the transform inserts is
//     "salt != 0" (level 2) or is keyed by salt (level 3). The zero-init /
//     never-stored invariant is what keeps those predicates constant.
//   * the level-3 dispatcher stores/loads an i32 state slot inside the
//     function through volatile accesses, which is what stops mem2reg/SROA
//     from recovering the original CFG at -O2.
//
//===----------------------------------------------------------------------===//

#ifndef AEGIS_CONTROL_FLOW_H
#define AEGIS_CONTROL_FLOW_H

#include "llvm/IR/Function.h"

#include <cstdint>

namespace aegis {

/// Internal zero global used by opaque predicates and as dispatcher salt.
extern const char *const kCffSaltName;

/// Module flags (MDNode of MDString) recording what the transform applied, so
/// the verifier can tell "erased by the optimizer" from "never selected" even
/// after inlining dropped the function attribute.
extern const char *const kBogusFlagName;
extern const char *const kFlattenedFlagName;

/// Deterministic 32-bit key used to encode dispatcher states. Pure function of
/// the module seed; never zero, so every encoded state differs from its index.
uint32_t controlFlowKey(uint32_t Seed);

/// Additional eligibility rules for flattening. Base rules (declaration,
/// optnone, naked, EH personality, musttail) are shared with the decoy
/// transform via ineligibilityReason().
llvm::StringRef flatteningIneligibilityReason(const llvm::Function &F);

bool eligibleForFlattening(const llvm::Function &F);

} // namespace aegis

#endif // AEGIS_CONTROL_FLOW_H
