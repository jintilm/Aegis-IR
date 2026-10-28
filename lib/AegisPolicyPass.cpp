//===- AegisPolicyPass.cpp - lower policy JSON to IR attributes -----------===//
//
// `aegis-policy<policy=FILE>` must run at the *start* of the pipeline, on
// freshly generated IR. It resolves policy entries against symbol names once,
// then pins the decision onto each function as `aegis.level` plus module
// flags `aegis.profile` / `aegis.seed`. Downstream transforms read only the
// attributes, so protection selection survives inlining, renaming and LTO.
//
// Unresolved entries (missing functions, declaration-only matches) are build
// errors: a typo in a policy must never silently leave code unprotected.
//
//===----------------------------------------------------------------------===//

#include "AegisPolicyPass.h"
#include "aegis/Policy.h"

#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/Demangle/Demangle.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Metadata.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace aegis {

AegisPolicyPass::AegisPolicyPass(std::string Path)
    : PolicyPath(std::move(Path)) {}

PreservedAnalyses AegisPolicyPass::run(Module &M, ModuleAnalysisManager &) {
  errs() << "[aegis-policy] policy=\"" << PolicyPath << "\"\n";

  Expected<Policy> Parsed = parsePolicyFile(PolicyPath);
  if (!Parsed) {
    std::string Msg =
        "[aegis-policy] invalid policy:\n" + toString(Parsed.takeError());
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }
  const Policy &P = *Parsed;

  errs() << "[aegis-policy] schema=" << P.SchemaVersion << " profile=\""
         << P.Profile << "\"";
  if (P.Seed)
    errs() << " seed=" << *P.Seed;
  errs() << "\n";

  M.addModuleFlag(Module::Warning, "aegis.profile",
                  MDString::get(M.getContext(), P.Profile));
  if (P.Seed)
    M.addModuleFlag(Module::Warning, "aegis.seed",
                    static_cast<uint32_t>(*P.Seed));

  // Index every function by exact symbol name; keep definitions for the
  // demangled-name fallback.
  DenseMap<StringRef, Function *> ByName;
  SmallVector<Function *, 64> Definitions;
  for (Function &F : M) {
    ByName[F.getName()] = &F;
    if (!F.isDeclaration())
      Definitions.push_back(&F);
  }

  unsigned Matched = 0;
  unsigned DeclarationOnly = 0;
  unsigned Missing = 0;

  for (const PolicyFunction &PF : P.Functions) {
    Function *F = nullptr;
    bool ViaDemangle = false;

    auto It = ByName.find(PF.Name);
    if (It != ByName.end()) {
      F = It->second;
    } else {
      // Fallback: compare against demangled names. A bare name matches the
      // demangled form up to its parameter list, e.g. "transform_value"
      // matches "transform_value(int)". Overloads make this ambiguous.
      Function *Unique = nullptr;
      bool Ambiguous = false;
      std::string Prefix = PF.Name + "(";
      for (Function *Cand : Definitions) {
        std::string Demangled = demangle(Cand->getName().str());
        if (Demangled == PF.Name || StringRef(Demangled).starts_with(Prefix)) {
          if (Unique) {
            Ambiguous = true;
            break;
          }
          Unique = Cand;
        }
      }
      if (Ambiguous) {
        errs() << "[aegis-policy] error: '" << PF.Name
               << "' matches multiple functions by demangled name; use the "
                  "mangled symbol name\n";
        ++Missing;
        continue;
      }
      if (Unique) {
        F = Unique;
        ViaDemangle = true;
      }
    }

    if (!F) {
      errs() << "[aegis-policy] error: not found: '" << PF.Name << "'\n";
      ++Missing;
      continue;
    }
    if (F->isDeclaration()) {
      errs() << "[aegis-policy] error: '" << PF.Name
             << "' matched a declaration, not a definition\n";
      ++DeclarationOnly;
      continue;
    }

    F->addFnAttr("aegis.level", std::to_string(PF.Level));
    errs() << "[aegis-policy] select " << F->getName() << " ("
           << demangle(F->getName().str()) << ") level=" << PF.Level;
    if (!PF.Reason.empty())
      errs() << " reason=\"" << PF.Reason << "\"";
    if (ViaDemangle)
      errs() << " (matched by demangled name)";
    errs() << "\n";
    ++Matched;
  }

  errs() << "[aegis-policy] summary: matched=" << Matched
         << " declaration-only=" << DeclarationOnly << " missing=" << Missing
         << "\n";

  if (Missing + DeclarationOnly > 0) {
    std::string Msg = "[aegis-policy] policy has " +
                      std::to_string(Missing + DeclarationOnly) +
                      " unresolved function(s); failing the build";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }

  // Function attributes and module flags changed: nothing is preserved.
  return PreservedAnalyses::none();
}

} // namespace aegis