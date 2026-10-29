//===- AegisVerifyPass.cpp - post-optimization decoy gate -----------------===//
//
// The optimizer is the adversary here: if -O2 removes a decoy function,
// drops a decoy string, folds the guard branch, or turns the guard global
// into something writable, the protection silently degraded. This pass turns
// all of those into build errors.
//
// Checks (all against the deterministic plan derived from the module seed):
//   1. every expected decoy function exists (exact name, or a `_vN` dedupe
//      suffix) and carries `aegis.decoy.fn` metadata;
//   2. decoy strings survive: enough globals carry `aegis.decoy.str`;
//   3. the guard global is internal, zero-initialised, and used only by
//      volatile loads (no stores — this is the unreachability argument);
//   4. every policy-selected, transform-eligible function still contains a
//      volatile guard load and a call into the decoy set.
//
//===----------------------------------------------------------------------===//

#include "AegisVerifyPass.h"
#include "DecoyCorpus.h"

#include "llvm/ADT/StringSet.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/GlobalVariable.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Metadata.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace {

bool hasDecoyFnMetadata(const Function &F) {
  return F.getMetadata("aegis.decoy.fn") != nullptr;
}

bool nameMatchesExpected(StringRef Actual, StringRef Expected) {
  if (Actual == Expected)
    return true;
  // Dedupe suffix used at injection time when a name collided.
  return Actual.starts_with((Expected + "_v").str());
}

} // namespace

namespace aegis {

namespace {

// Module-flag values are nested MDNodes whose shape depends on how the flag was
// added, so walk the whole tree instead of assuming a flat operand list.
void collectStrings(const Metadata *MD, StringSet<> &Out) {
  if (const auto *S = dyn_cast<MDString>(MD)) {
    Out.insert(S->getString());
    return;
  }
  if (const auto *N = dyn_cast<MDNode>(MD))
    for (const Metadata *Op : N->operands())
      collectStrings(Op, Out);
}

} // namespace

PreservedAnalyses AegisVerifyPass::run(Module &M, ModuleAnalysisManager &) {
  const uint32_t Seed = moduleSeed(M);
  const DecoyPlan Plan = buildDecoyPlan(Seed);

  errs() << "[aegis-verify] seed=" << Seed
         << " expected decoy_functions=" << Plan.FunctionNames.size()
         << " decoy_strings=" << Plan.Strings.size() << "\n";

  std::vector<std::string> Problems;

  // Collect decoy functions actually present (by metadata).
  SmallVector<Function *, 8> DecoyFns;
  for (Function &F : M)
    if (hasDecoyFnMetadata(F) && !F.isDeclaration())
      DecoyFns.push_back(&F);
  StringSet<> DecoyNames;
  for (Function *F : DecoyFns)
    DecoyNames.insert(F->getName());

  // 1. Expected functions present.
  unsigned FoundFns = 0;
  for (const std::string &Expected : Plan.FunctionNames) {
    bool Found = false;
    for (Function *F : DecoyFns) {
      if (nameMatchesExpected(F->getName(), Expected)) {
        Found = true;
        break;
      }
    }
    if (Found) {
      ++FoundFns;
    } else {
      Problems.push_back("decoy function missing: '" + Expected +
                         "' (optimizer removed it or the seed changed)");
    }
  }

  // 2. Decoy strings present.
  unsigned FoundStrs = 0;
  for (GlobalVariable &GV : M.globals())
    if (GV.getMetadata("aegis.decoy.str"))
      ++FoundStrs;
  if (FoundStrs < Plan.Strings.size())
    Problems.push_back("decoy strings missing: expected at least " +
                       std::to_string(Plan.Strings.size()) + ", found " +
                       std::to_string(FoundStrs));

  // 3. Guard global integrity.
  const GlobalVariable *Guard = M.getNamedGlobal(kGuardGlobalName);
  if (!Guard) {
    Problems.push_back(std::string("guard global missing: ") +
                       kGuardGlobalName);
  } else {
    if (!Guard->hasInternalLinkage())
      Problems.push_back("guard global must have internal linkage");
    const Constant *Init =
        Guard->hasInitializer() ? Guard->getInitializer() : nullptr;
    const auto *CI = dyn_cast_or_null<ConstantInt>(Init);
    if (!CI || !CI->isZero())
      Problems.push_back("guard global must be zero-initialised");
    for (const User *U : Guard->users()) {
      const auto *LI = dyn_cast<LoadInst>(U);
      if (!LI || !LI->isVolatile())
        Problems.push_back(
            "guard global used by something other than a volatile load "
            "(stores would break the unreachability argument)");
    }
  }

  // 4. Every function the transform guarded still carries the guard load and a
  //    decoy call. The transform records the set in a module flag because a
  //    function that was inlined away loses its `aegis.level` attribute; the
  //    flag lets us tell "erased" (a regression) from "never selected".
  StringSet<> ExpectedGuarded;
  if (const Metadata *Flag = M.getModuleFlag(kGuardedFlagName))
    collectStrings(Flag, ExpectedGuarded);

  auto hasGuardAndDecoy = [&](const Function &F) {
    bool HasGuardLoad = false;
    bool HasDecoyCall = false;
    for (const Instruction &I : instructions(F)) {
      if (const auto *LI = dyn_cast<LoadInst>(&I)) {
        if (LI->isVolatile() && LI->getPointerOperand() == Guard)
          HasGuardLoad = true;
      }
      if (const auto *CB = dyn_cast<CallBase>(&I)) {
        if (const Function *Callee = CB->getCalledFunction())
          if (DecoyNames.contains(Callee->getName()))
            HasDecoyCall = true;
      }
    }
    return HasGuardLoad && HasDecoyCall;
  };

  unsigned Selected = 0;
  unsigned GuardedOk = 0;
  unsigned RemovedByInlining = 0;
  unsigned GuardLoads = 0;
  for (const auto &Entry : ExpectedGuarded) {
    ++Selected;
    Function *F = M.getFunction(Entry.getKey());
    if (!F || F->isDeclaration()) {
      // Inlined away: its `aegis.level` attribute went with it, so the
      // per-function check cannot apply. The module-wide load count below is
      // what keeps this fail-closed.
      ++RemovedByInlining;
      continue;
    }
    if (hasGuardAndDecoy(*F)) {
      ++GuardedOk;
    } else {
      Problems.push_back(
          "guarded function '" + Entry.getKey().str() +
          "' lost its decoy branch (guard load or decoy call missing)");
    }
  }

  // Each surviving copy of a guarded body contains a volatile guard load (the
  // load is never merged or folded), so fewer loads than guarded functions
  // means at least one decoy branch was erased along the way.
  for (const Function &F : M)
    if (!F.isDeclaration())
      for (const Instruction &I : instructions(F))
        if (const auto *LI = dyn_cast<LoadInst>(&I))
          if (LI->isVolatile() && LI->getPointerOperand() == Guard)
            ++GuardLoads;
  if (GuardLoads < Selected)
    Problems.push_back(
        "only " + std::to_string(GuardLoads) + " volatile guard load(s) for " +
        std::to_string(Selected) +
        " guarded function(s): at least one decoy branch was erased (if the "
        "Aegis passes ran after inlining this also happens; run them on "
        "frontend IR, before default<O2>)");

  // A level>=1 function the decoy pass never saw (attribute added later, or
  // passes reordered) is a build error: the policy claims protection that is
  // not there.
  for (const Function &F : M) {
    if (functionLevel(F) < 1 || !eligibleForDecoys(F))
      continue;
    if (ExpectedGuarded.contains(F.getName()))
      continue;
    Problems.push_back("selected function '" + F.getName().str() +
                       "' was never guarded (run aegis-decoys after "
                       "aegis-policy and before aegis-verify)");
  }

  errs() << "[aegis-verify] decoy functions present: " << FoundFns << "/"
         << Plan.FunctionNames.size() << " | decoy strings: " << FoundStrs
         << "/" << Plan.Strings.size() << " | guard loads: " << GuardLoads
         << " | guarded functions: " << GuardedOk << "/" << Selected;
  if (RemovedByInlining)
    errs() << " (" << RemovedByInlining << " inlined away)";
  errs() << "\n";

  if (!Problems.empty()) {
    for (const std::string &P : Problems)
      errs() << "[aegis-verify] error: " << P << "\n";
    std::string Msg = "[aegis-verify] " + std::to_string(Problems.size()) +
                      " problem(s); protection degraded, failing the build";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }

  errs() << "[aegis-verify] OK\n";
  return PreservedAnalyses::all();
}

} // namespace aegis