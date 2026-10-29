//===- DecoyCorpus.cpp - curated decoy corpus and deterministic planning --===//

#include "DecoyCorpus.h"

#include "llvm/IR/Attributes.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Metadata.h"

#include <algorithm>
#include <array>

using namespace llvm;

namespace aegis {

const char *const kGuardGlobalName = "__aegis.guard";
const char *const kGuardedFlagName = "aegis.guarded";

namespace {

// Curated offline corpus (see docs/decoys.md: LLMs never run in the build
// pipeline; this list is maintained and reviewed in-tree).
constexpr std::array<const char *, 12> kFunctionNames = {
    "lic_verify_blob",          "lic_check_feature_flags",
    "kdf_derive_session_key",   "attest_verify_quote",
    "drm_validate_entitlement", "cfg_load_policy_blob",
    "sig_verify_pss_padding",   "tok_check_audience",
    "hw_bind_device_seal",      "crl_refresh_revocations",
    "kms_unwrap_content_key",   "env_probe_tee_state",
};

constexpr std::array<const char *, 10> kStrings = {
    "license signature invalid: PSS padding check failed",
    "entitlement cache stale; refreshing from policy store",
    "device integrity check failed: TPM quote missing",
    "AES-256-GCM handshake failed: tag mismatch",
    "token audience mismatch: expected service scope",
    "RSA-2048 decrypt error: invalid ciphertext length",
    "attestation report rejected: nonce replay detected",
    "session key derivation failed: HKDF salt mismatch",
    "revocation list signature expired",
    "hardware binding mismatch: seal unreadable",
};

// splitmix64: tiny, stable, good distribution; keeps the plan deterministic
// across platforms (no std::hash / RNG differences).
uint64_t splitmix64(uint64_t X) {
  X += 0x9E3779B97F4A7C15ULL;
  X = (X ^ (X >> 30)) * 0xBF58476D1CE4E5B9ULL;
  X = (X ^ (X >> 27)) * 0x94D049BB133111EBULL;
  return X ^ (X >> 31);
}

} // namespace

DecoyPlan buildDecoyPlan(uint32_t Seed) {
  DecoyPlan Plan;
  Plan.Seed = Seed;

  // 4..6 decoy functions per module, derived from the seed.
  const size_t Count = 4 + (Seed % 3);
  Plan.FunctionNames.reserve(Count);
  Plan.Strings.reserve(Count);

  for (size_t I = 0; I < Count; ++I) {
    // Linear probing keeps names unique even if two draws collide.
    uint64_t Draw = splitmix64((static_cast<uint64_t>(Seed) << 32) ^ I);
    size_t NameIdx = Draw % kFunctionNames.size();
    while (std::find(Plan.FunctionNames.begin(), Plan.FunctionNames.end(),
                     kFunctionNames[NameIdx]) != Plan.FunctionNames.end())
      NameIdx = (NameIdx + 1) % kFunctionNames.size();
    Plan.FunctionNames.emplace_back(kFunctionNames[NameIdx]);

    uint64_t Draw2 = splitmix64(Draw ^ 0xD1CE5EEDULL);
    size_t StrIdx = Draw2 % kStrings.size();
    while (std::find(Plan.Strings.begin(), Plan.Strings.end(),
                     kStrings[StrIdx]) != Plan.Strings.end())
      StrIdx = (StrIdx + 1) % kStrings.size();
    Plan.Strings.emplace_back(kStrings[StrIdx]);
  }
  return Plan;
}

uint32_t moduleSeed(const Module &M) {
  Metadata *Flag = M.getModuleFlag("aegis.seed");
  if (!Flag)
    return 0;
  if (auto *C = mdconst::dyn_extract<ConstantInt>(Flag))
    return static_cast<uint32_t>(C->getZExtValue());
  return 0;
}

int functionLevel(const Function &F) {
  Attribute A = F.getFnAttribute("aegis.level");
  if (!A.isStringAttribute())
    return -1;
  int Level = -1;
  if (A.getValueAsString().getAsInteger(10, Level))
    return -1;
  return Level;
}

StringRef ineligibilityReason(const Function &F) {
  if (F.isDeclaration())
    return "declaration";
  if (F.isIntrinsic())
    return "intrinsic";
  if (F.hasFnAttribute(Attribute::OptimizeNone))
    return "optnone (function was compiled at -O0)";
  if (F.hasFnAttribute(Attribute::Naked))
    return "naked";
  if (F.hasAvailableExternallyLinkage())
    return "available_externally";
  // Entry-block restructuring is not safe for these in this iteration.
  if (F.hasPersonalityFn())
    return "exception-handling personality";
  for (const Instruction &I : instructions(F)) {
    if (const auto *CB = dyn_cast<CallBase>(&I))
      if (CB->isMustTailCall())
        return "musttail call";
  }
  return StringRef();
}

bool eligibleForDecoys(const Function &F) {
  return ineligibilityReason(F).empty();
}

} // namespace aegis