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
#include "ControlFlow.h"
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

bool isVolatileLoadOf(const Instruction &I, const GlobalVariable *GV) {
  const auto *LI = dyn_cast<LoadInst>(&I);
  return LI && LI->isVolatile() && LI->getPointerOperand() == GV;
}

// The optimizer may fold two volatile loads of different zero globals into a
// select of pointers plus one load. That keeps the unreachability argument
// intact, so the use check follows select/GEP/bitcast chains and rejects only
// paths that end in a store or a non-volatile read.
bool onlyVolatileReads(const Value *V, unsigned Depth = 0) {
  if (Depth > 8)
    return false;
  for (const User *U : V->users()) {
    if (const auto *LI = dyn_cast<LoadInst>(U)) {
      if (!LI->isVolatile())
        return false;
      continue;
    }
    if (isa<SelectInst>(U) || isa<GetElementPtrInst>(U) ||
        isa<BitCastInst>(U) || isa<ConstantExpr>(U)) {
      if (!onlyVolatileReads(U, Depth + 1))
        return false;
      continue;
    }
    return false;
  }
  return true;
}

bool hasSaltLoad(const Function &F, const GlobalVariable *Salt) {
  if (!Salt)
    return false;
  for (const Instruction &I : instructions(F))
    if (isVolatileLoadOf(I, Salt))
      return true;
  return false;
}

// Structural check for a level-2 function: the volatile salt load must reach a
// conditional branch whose taken arm ends in `unreachable`. Merely finding a
// volatile load is not enough — that would pass a build where the optimizer
// kept the load but dropped the bogus edge.
bool hasLiveOpaqueEdge(const Function &F, const GlobalVariable *Salt) {
  if (!Salt)
    return false;
  for (const BasicBlock &BB : F) {
    bool HasSaltLoad = false;
    for (const Instruction &I : BB)
      HasSaltLoad |= isVolatileLoadOf(I, Salt);
    if (!HasSaltLoad)
      continue;
    const auto *BI = dyn_cast<CondBrInst>(BB.getTerminator());
    if (!BI)
      continue;
    for (unsigned I = 0; I < 2; ++I) {
      const BasicBlock *Arm = BI->getSuccessor(I);
      // The dead arm must be a block that reaches `unreachable` without
      // returning to the live path.
      if (isa<UnreachableInst>(Arm->getTerminator()))
        return true;
      if (const auto *Inner = dyn_cast<UncondBrInst>(Arm->getTerminator()))
        if (isa<UnreachableInst>(Inner->getSuccessor(0)->getTerminator()))
          return true;
    }
  }
  return false;
}

// Structural check for a level-3 function: the switch condition must be
// derived from a volatile i32 load in the same block, i.e. the dispatcher
// still reads the state slot. A switch left behind after the state load was
// replaced by a constant is not a flattened control flow.
bool derivedFromVolatileLoad(const Value *V, const BasicBlock &BB,
                             unsigned Depth = 0) {
  if (Depth > 8 || !V)
    return false;
  if (const auto *LI = dyn_cast<LoadInst>(V))
    return LI->isVolatile() && LI->getType()->isIntegerTy(32) &&
           LI->getParent() == &BB;
  if (const auto *I = dyn_cast<Instruction>(V)) {
    if (isa<BinaryOperator>(I) || isa<CastInst>(I) || isa<SelectInst>(I))
      for (const Value *Op : I->operands())
        if (derivedFromVolatileLoad(Op, BB, Depth + 1))
          return true;
  }
  return false;
}

bool hasDispatchSwitch(const Function &F) {
  for (const BasicBlock &BB : F) {
    const auto *SI = dyn_cast<SwitchInst>(BB.getTerminator());
    if (!SI || SI->getNumCases() < 2)
      continue;
    if (derivedFromVolatileLoad(SI->getCondition(), BB))
      return true;
  }
  return false;
}

// A flattened function owns one i32 state slot accessed through volatile
// load/store pairs. Volatile access is what stops mem2reg/SROA from turning
// the dispatcher back into the original CFG.
unsigned countFlattenedStates(const Function &F) {
  unsigned States = 0;
  for (const Instruction &I : instructions(F)) {
    const auto *AI = dyn_cast<AllocaInst>(&I);
    if (!AI || !AI->getAllocatedType()->isIntegerTy(32))
      continue;
    // The name survives inlining (with a suffix); requiring it avoids
    // counting an unrelated user-level `volatile int` local as a state slot.
    if (!AI->getName().starts_with("aegis.state"))
      continue;
    bool HasVolatileLoad = false;
    bool HasVolatileStore = false;
    for (const User *U : AI->users()) {
      if (const auto *LI = dyn_cast<LoadInst>(U))
        HasVolatileLoad |= LI->isVolatile();
      if (const auto *SI = dyn_cast<StoreInst>(U))
        HasVolatileStore |= SI->isVolatile() && SI->getPointerOperand() == AI;
    }
    if (HasVolatileLoad && HasVolatileStore)
      ++States;
  }
  return States;
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
  // A truly unselected module needs no decoys. Positive policy intent and
  // transform records survive inlining, so their presence must still force
  // the full gate even when no aegis.level attributes remain. Also recognize
  // older transformed IR and attribute-only pipelines without the new flag.
  bool ProtectionExpected =
      M.getModuleFlag(kProtectionRequestedFlagName) ||
      M.getModuleFlag(kGuardedFlagName) || M.getModuleFlag(kBogusFlagName) ||
      M.getModuleFlag(kFlattenedFlagName) ||
      M.getNamedGlobal(kGuardGlobalName) || M.getNamedGlobal(kCffSaltName);
  for (const Function &F : M)
    ProtectionExpected |= functionLevel(F) >= 1 || hasDecoyFnMetadata(F);
  for (const GlobalVariable &GV : M.globals())
    ProtectionExpected |= GV.getMetadata("aegis.decoy.str") != nullptr;
  if (!ProtectionExpected) {
    errs() << "[aegis-verify] OK: no protection requested; module unchanged\n";
    return PreservedAnalyses::all();
  }

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
    if (!onlyVolatileReads(Guard))
      Problems.push_back(
          "guard global used by something other than a volatile load "
          "(stores would break the unreachability argument)");
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

  // 5. Level 2/3 control-flow artifacts. The transform records what it
  //    applied; the optimizer must not have removed any of it.
  StringSet<> ExpectedBogus;
  StringSet<> ExpectedFlattened;
  if (const Metadata *Flag = M.getModuleFlag(kBogusFlagName))
    collectStrings(Flag, ExpectedBogus);
  if (const Metadata *Flag = M.getModuleFlag(kFlattenedFlagName))
    collectStrings(Flag, ExpectedFlattened);

  GlobalVariable *Salt = M.getNamedGlobal(kCffSaltName);
  unsigned SaltLoads = 0;
  if (!ExpectedBogus.empty() || !ExpectedFlattened.empty()) {
    if (!Salt) {
      Problems.push_back(std::string("control-flow salt missing: ") +
                         kCffSaltName);
    } else {
      if (!Salt->hasInternalLinkage())
        Problems.push_back("control-flow salt must have internal linkage");
      const Constant *Init =
          Salt->hasInitializer() ? Salt->getInitializer() : nullptr;
      const auto *CI = dyn_cast_or_null<ConstantInt>(Init);
      if (!CI || !CI->isZero())
        Problems.push_back("control-flow salt must be zero-initialised");
      if (!onlyVolatileReads(Salt))
        Problems.push_back(
            "control-flow salt used by something other than a volatile load "
            "(stores would make the opaque predicates live)");
      for (const Function &F : M)
        if (!F.isDeclaration())
          for (const Instruction &I : instructions(F))
            if (isVolatileLoadOf(I, Salt))
              ++SaltLoads;
    }
  }

  unsigned BogusOk = 0;
  unsigned BogusInlined = 0;
  if (!ExpectedBogus.empty()) {
    for (const auto &Entry : ExpectedBogus) {
      Function *F = M.getFunction(Entry.getKey());
      if (!F || F->isDeclaration()) {
        ++BogusInlined;
        continue;
      }
      // Flattening replaces every branch with a dispatcher round trip, so the
      // level-2 shape (salt load feeding a branch to an unreachable arm) no
      // longer exists for a level-3 function: its opaque predicates are the
      // dispatcher and the encoded case constants. Those are checked below by
      // the flattened-function check.
      if (ExpectedFlattened.contains(Entry.getKey()))
        continue;
      if (hasLiveOpaqueEdge(*F, Salt))
        ++BogusOk;
      else
        Problems.push_back("level-2 function '" + Entry.getKey().str() +
                           "' lost its opaque-predicate edge (no volatile "
                           "salt load feeding a branch to an unreachable arm)");
    }
    if (SaltLoads < ExpectedBogus.size())
      Problems.push_back(
          "only " + std::to_string(SaltLoads) + " volatile salt load(s) for " +
          std::to_string(ExpectedBogus.size()) +
          " level-2 function(s): at least one opaque edge was erased");
  }

  unsigned FlattenedOk = 0;
  unsigned FlattenedInlined = 0;
  unsigned FlattenedStates = 0;
  if (!ExpectedFlattened.empty()) {
    for (const Function &F : M)
      if (!F.isDeclaration())
        FlattenedStates += countFlattenedStates(F);
    for (const auto &Entry : ExpectedFlattened) {
      Function *F = M.getFunction(Entry.getKey());
      if (!F || F->isDeclaration()) {
        ++FlattenedInlined;
        continue;
      }
      if (countFlattenedStates(*F) > 0 && hasDispatchSwitch(*F))
        ++FlattenedOk;
      else
        Problems.push_back("level-3 function '" + Entry.getKey().str() +
                           "' lost its dispatch (the volatile state load no "
                           "longer selects a switch; the optimizer recovered "
                           "the original CFG)");
    }
    if (FlattenedStates < ExpectedFlattened.size())
      Problems.push_back(
          "only " + std::to_string(FlattenedStates) +
          " volatile dispatch state slot(s) for " +
          std::to_string(ExpectedFlattened.size()) +
          " flattened function(s): at least one state machine was erased");
  }

  // A level>=2 function that carries the attribute but was never recorded is
  // the same class of lie as an unguarded level-1 function.
  for (const Function &F : M) {
    const int Level = functionLevel(F);
    if (Level < 2 || !eligibleForDecoys(F))
      continue;
    if (Level >= 3) {
      if (!ExpectedFlattened.contains(F.getName()))
        Problems.push_back("level-3 function '" + F.getName().str() +
                           "' was never flattened (run aegis-cff after "
                           "aegis-decoys and before aegis-verify)");
    } else if (!ExpectedBogus.contains(F.getName())) {
      Problems.push_back("level-2 function '" + F.getName().str() +
                         "' was never transformed (run aegis-cff after "
                         "aegis-decoys and before aegis-verify)");
    }
  }

  errs() << "[aegis-verify] decoy functions present: " << FoundFns << "/"
         << Plan.FunctionNames.size() << " | decoy strings: " << FoundStrs
         << "/" << Plan.Strings.size() << " | guard loads: " << GuardLoads
         << " | guarded functions: " << GuardedOk << "/" << Selected;
  if (RemovedByInlining)
    errs() << " (" << RemovedByInlining << " inlined away)";
  errs() << "\n";
  if (!ExpectedBogus.empty() || !ExpectedFlattened.empty()) {
    errs() << "[aegis-verify] salt loads: " << SaltLoads
           << " | level-2 functions: " << BogusOk << "/"
           << ExpectedBogus.size();
    if (BogusInlined)
      errs() << " (" << BogusInlined << " inlined away)";
    errs() << " | flattened: " << FlattenedOk << "/" << ExpectedFlattened.size()
           << " (" << FlattenedStates << " state slots";
    if (FlattenedInlined)
      errs() << ", " << FlattenedInlined << " inlined away";
    errs() << ")\n";
  }

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
