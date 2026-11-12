//===- Policy.h - aegis policy model and JSON loader ----------------------===//
//
// Policy is the single source of truth for "which functions are protected,
// at which tier, and why". The JSON form is parsed once at pipeline start by
// the aegis-policy pass, which lowers it to function attributes
// (`aegis.level`) and module flags (`aegis.profile`, `aegis.seed`). All
// downstream transforms read the attributes only, so selection survives
// inlining and LTO even when symbol names do not.
//
//===----------------------------------------------------------------------===//

#ifndef AEGIS_POLICY_H
#define AEGIS_POLICY_H

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace aegis {

/// One protected function entry.
struct PolicyFunction {
  /// Symbol name as it appears in the IR (mangled for C++), or a demangled
  /// name compared against `llvm::demangle()` output (see docs/policy.md).
  std::string Name;
  /// Transform strength: 0 = explicitly unprotected, 1..3 increase local
  /// protection cost. These are policy levels, not threat-model tiers.
  int Level = 0;
  /// Free-form justification recorded in selection reports.
  std::string Reason;
};

/// Engineering budget targets. Parsed and reported now; enforced by CI
/// gates in later stages.
struct PolicyLimits {
  std::optional<int64_t> MaxBinaryGrowthPercent;
  std::optional<int64_t> MaxP95SlowdownPercent;
};

struct Policy {
  int64_t SchemaVersion = 0;
  std::string Profile; // dev | release | research | debug
  std::optional<uint32_t> Seed;
  std::vector<PolicyFunction> Functions;
  PolicyLimits Limits;
};

/// Parse and validate an Aegis policy file.
///
/// On failure the returned error message contains every validation problem
/// found, one per line, so a single run reports all mistakes.
llvm::Expected<Policy> parsePolicyFile(llvm::StringRef Path);

/// Parse and validate a policy from an in-memory JSON buffer. Exposed for
/// unit tests; `Path` is used only in diagnostics.
llvm::Expected<Policy> parsePolicy(llvm::StringRef JSON, llvm::StringRef Path);

} // namespace aegis

#endif // AEGIS_POLICY_H
