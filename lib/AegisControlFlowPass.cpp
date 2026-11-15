//===- AegisControlFlowPass.cpp - level 2/3 control-flow transforms -------===//
//
// Level 2 (every policy function at level >= 2):
//   * a live split at the decoy guard: the condition is derived from a
//     function argument, and both arms only perform volatile loads before
//     rejoining. Program output is unchanged, but the executed edge now
//     depends on the input, which is the one Tier-2-class property this
//     compile-time transform can honestly provide;
//   * one or two bogus edges deeper in the function. Their predicate is
//     `volatile load @__aegis.cff.salt != 0`; the global is internal, zero
//     initialised and never stored to, so the arm never executes.
//
// Level 3 (level >= 3) additionally flattens the function:
//   * PHIs are demoted to stack slots;
//   * the entry block is replaced by a prologue that initialises a state slot
//     and jumps to a dispatcher;
//   * every branch becomes a volatile state store; the dispatcher loads the
//     state, XORs it with a salt-derived key, and switches on the result.
//   Volatile accesses stop mem2reg/SROA from turning the state machine back
//   into the original CFG at -O2.
//
// What this is not: the threat model's Tier-3 "semantics removal" (cloud/TEE).
// Flattening raises static reconstruction cost; it does not hide the
// dispatcher from a dynamic trace, and the docs say so.
//
//===----------------------------------------------------------------------===//

#include "AegisControlFlowPass.h"
#include "ControlFlow.h"
#include "DecoyCorpus.h"

#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Transforms/Utils/BasicBlockUtils.h"
#include "llvm/Transforms/Utils/Local.h"

#include <algorithm>
#include <string>
#include <utility>

using namespace llvm;

namespace {

bool startsWithAegis(const BasicBlock &BB) {
  return BB.getName().starts_with("aegis.");
}

bool isVolatileLoadOf(const Instruction &I, const GlobalVariable *GV) {
  const auto *LI = dyn_cast<LoadInst>(&I);
  return LI && LI->isVolatile() && LI->getPointerOperand() == GV;
}

// Locate the decoy guard branch inserted by aegis-decoys. Returns false when
// the pass ordering is wrong; the caller treats that as a build error.
bool findGuardBranch(Function &F, const GlobalVariable *Guard, CondBrInst *&Br,
                     unsigned &BodyIdx) {
  for (BasicBlock &BB : F) {
    auto *BI = dyn_cast<CondBrInst>(BB.getTerminator());
    if (!BI)
      continue;
    bool HasGuardLoad = false;
    for (const Instruction &I : BB)
      if (isVolatileLoadOf(I, Guard))
        HasGuardLoad = true;
    if (!HasGuardLoad)
      continue;
    for (unsigned I = 0; I < 2; ++I) {
      if (BI->getSuccessor(I)->getName().starts_with("aegis.decoy")) {
        Br = BI;
        BodyIdx = 1 - I;
        return true;
      }
    }
  }
  return false;
}

// Insert the input-driven live split between the guard check and the body.
// Arm A performs two volatile loads (guard + salt), arm B one; the differing
// side-effect counts stop SimplifyCFG from folding the arms into a select of
// pointers plus a single load (which it does to two identical single-load
// arms).
void injectLiveSplit(Function &F, GlobalVariable *Guard, GlobalVariable *Salt) {
  LLVMContext &Ctx = F.getContext();
  Type *I32 = Type::getInt32Ty(Ctx);

  CondBrInst *GuardBr = nullptr;
  unsigned BodyIdx = 0;
  if (!findGuardBranch(F, Guard, GuardBr, BodyIdx)) {
    std::string Msg = "[aegis-cff] no decoy guard branch in '" +
                      F.getName().str() +
                      "'; run aegis-decoys before aegis-cff";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }

  BasicBlock *GuardBB = GuardBr->getParent();
  BasicBlock *Body = GuardBr->getSuccessor(BodyIdx);

  BasicBlock *Live = BasicBlock::Create(Ctx, "aegis.live", &F, Body);
  BasicBlock *ArmA = BasicBlock::Create(Ctx, "aegis.live.a", &F, Body);
  BasicBlock *ArmB = BasicBlock::Create(Ctx, "aegis.live.b", &F, Body);
  GuardBr->setSuccessor(BodyIdx, Live);

  // Body's PHIs used to receive a value from GuardBB. Both new arms forward
  // the same values, so the merge stays correct.
  for (PHINode &PN : Body->phis()) {
    const int Idx = PN.getBasicBlockIndex(GuardBB);
    if (Idx < 0)
      continue;
    Value *Incoming = PN.getIncomingValue(static_cast<unsigned>(Idx));
    PN.removeIncomingValue(static_cast<unsigned>(Idx));
    PN.addIncoming(Incoming, ArmA);
    PN.addIncoming(Incoming, ArmB);
  }

  IRBuilder<> LB(Live);
  Value *Runtime = nullptr;
  for (Argument &Arg : F.args()) {
    Type *T = Arg.getType();
    if (T->isIntegerTy() && T->getIntegerBitWidth() >= 8) {
      Runtime = &Arg;
      break;
    }
  }
  if (!Runtime)
    for (Argument &Arg : F.args())
      if (Arg.getType()->isPointerTy())
        Runtime = &Arg;

  Value *Predicate = nullptr;
  if (Runtime) {
    if (Runtime->getType()->isPointerTy())
      Runtime = LB.CreatePtrToInt(Runtime, Type::getInt64Ty(Ctx));
    else if (Runtime->getType()->getIntegerBitWidth() < 8)
      Runtime = LB.CreateZExt(Runtime, I32);
    Type *T = Runtime->getType();
    const unsigned Width = T->getIntegerBitWidth();
    Value *Shifted =
        LB.CreateLShr(Runtime, ConstantInt::get(T, std::max(1u, Width / 2)));
    Value *Mixed = LB.CreateXor(Runtime, Shifted);
    Value *Bit = LB.CreateAnd(Mixed, ConstantInt::get(T, 1));
    Predicate = LB.CreateICmpNE(Bit, ConstantInt::get(T, 0), "aegis.live.p");
  } else {
    // No runtime value to branch on: fall back to the salt predicate. The
    // split survives, but it is statically dead, so the doc calls this out.
    LoadInst *SL = LB.CreateLoad(I32, Salt, "aegis.live.salt");
    SL->setVolatile(true);
    Predicate = LB.CreateICmpNE(SL, ConstantInt::get(I32, 0), "aegis.live.p");
  }
  LB.CreateCondBr(Predicate, ArmA, ArmB);

  {
    IRBuilder<> AB(ArmA);
    // Two volatile loads vs. one in the other arm: the arms have different
    // side-effect counts, so SimplifyCFG cannot fold them into a select of
    // pointers (which is what it does to two single-load arms).
    LoadInst *L1 = AB.CreateLoad(I32, Guard, "aegis.live.g");
    L1->setVolatile(true);
    LoadInst *L2 = AB.CreateLoad(I32, Salt, "aegis.live.s");
    L2->setVolatile(true);
    (void)AB.CreateXor(L1, L2);
    AB.CreateBr(Body);
  }
  {
    IRBuilder<> BB(ArmB);
    LoadInst *L = BB.CreateLoad(I32, Salt, "aegis.live.s");
    L->setVolatile(true);
    BB.CreateBr(Body);
  }
}

// Insert opaque-predicate bogus edges. Returns how many were inserted.
unsigned injectBogus(Function &F, GlobalVariable *Salt,
                     ArrayRef<Function *> DecoyFns, uint32_t Seed) {
  LLVMContext &Ctx = F.getContext();
  Type *I32 = Type::getInt32Ty(Ctx);

  SmallVector<BasicBlock *, 16> Candidates;
  for (BasicBlock &BB : F) {
    if (&BB == &F.getEntryBlock())
      continue;
    if (startsWithAegis(BB))
      continue;
    Candidates.push_back(&BB);
  }
  if (Candidates.empty())
    return 0;

  SmallVector<std::pair<uint64_t, BasicBlock *>, 16> Keyed;
  Keyed.reserve(Candidates.size());
  for (size_t I = 0; I < Candidates.size(); ++I) {
    uint64_t X = static_cast<uint64_t>(Seed) ^ (I * 0x9E3779B97F4A7C15ULL);
    X += 0x9E3779B97F4A7C15ULL;
    X = (X ^ (X >> 30)) * 0xBF58476D1CE4E5B9ULL;
    X = (X ^ (X >> 27)) * 0x94D049BB133111EBULL;
    Keyed.push_back({X ^ (X >> 31), Candidates[I]});
  }
  llvm::sort(Keyed,
             [](const auto &L, const auto &R) { return L.first < R.first; });

  unsigned Count = 1 + (Seed % 2);
  Count = std::min<unsigned>(Count, Keyed.size());

  for (unsigned I = 0; I < Count; ++I) {
    BasicBlock *BB = Keyed[I].second;
    BasicBlock *Real = SplitBlock(BB, BB->getTerminator()->getIterator());
    Real->setName("aegis.real");
    BB->getTerminator()->eraseFromParent();

    IRBuilder<> B(BB);
    LoadInst *SL = B.CreateLoad(I32, Salt, "aegis.bogus.salt");
    SL->setVolatile(true);
    Value *NZ = B.CreateICmpNE(SL, ConstantInt::get(I32, 0), "aegis.bogus.c");

    BasicBlock *Junk = BasicBlock::Create(Ctx, "aegis.bogus", &F, Real);
    B.CreateCondBr(NZ, Junk, Real);

    IRBuilder<> JB(Junk);
    const unsigned Calls = 1 + (Seed % 2);
    for (unsigned K = 0; K < Calls; ++K) {
      Function *DF = DecoyFns[(Seed + K + I) % DecoyFns.size()];
      JB.CreateCall(DF, {ConstantPointerNull::get(PointerType::getUnqual(Ctx)),
                         ConstantInt::get(Type::getInt64Ty(Ctx), 0)});
    }
    Value *H = JB.CreateMul(SL, ConstantInt::get(I32, 0x9E3779B9u));
    H = JB.CreateXor(H, ConstantInt::get(I32, 0x85EBCA6Bu));
    H = JB.CreateAdd(H, ConstantInt::get(I32, 0xC2B2AE35u));
    (void)JB.CreateICmpEQ(H, ConstantInt::get(I32, 0x27D4EB2Fu));
    JB.CreateUnreachable();
  }
  return Count;
}

// Flattening gives the dispatcher an edge to every case block, which destroys
// the static dominance relations that made cross-block SSA values legal. PHIs
// are handled separately; everything else that is live across a block boundary
// is demoted to a stack slot before the CFG is rewritten.
void demoteCrossBlockValues(Function &F) {
  SmallVector<Instruction *, 64> ToDemote;
  for (BasicBlock &BB : F)
    for (Instruction &I : BB) {
      if (I.getType()->isVoidTy() || I.getType()->isTokenTy() ||
          I.getType()->isMetadataTy())
        continue;
      if (isa<PHINode>(I) || isa<AllocaInst>(I) || I.isTerminator())
        continue;
      if (I.use_empty())
        continue;
      bool CrossesBlock = false;
      for (const User *U : I.users())
        if (const auto *UI = dyn_cast<Instruction>(U))
          if (UI->getParent() != &BB) {
            CrossesBlock = true;
            break;
          }
      if (CrossesBlock)
        ToDemote.push_back(&I);
    }
  for (Instruction *I : ToDemote)
    DemoteRegToStack(*I);
}

// Rewrite a function into a volatile state machine. Returns false when the
// function contains a construct the rewrite cannot handle (the caller has
// already pre-checked eligibility, so this is a defensive failure).
bool flattenFunction(Function &F, GlobalVariable *Salt, uint32_t Key) {
  LLVMContext &Ctx = F.getContext();
  Type *I32 = Type::getInt32Ty(Ctx);

  // The CFG rewrite invalidates SSA edges, so PHIs become stack slots first.
  SmallVector<PHINode *, 16> Phis;
  for (BasicBlock &BB : F)
    for (PHINode &PN : BB.phis())
      Phis.push_back(&PN);
  for (PHINode *PN : Phis)
    DemotePHIToStack(PN);
  demoteCrossBlockValues(F);

  BasicBlock &OldEntry = F.getEntryBlock();
  BasicBlock *NewEntry = BasicBlock::Create(Ctx, "aegis.entry", &F, &OldEntry);

  // Static allocas must stay in the entry block; the dispatcher loops, so
  // leaving them in a case block would allocate per iteration.
  SmallVector<AllocaInst *, 8> Allocas;
  for (Instruction &I : OldEntry)
    if (auto *AI = dyn_cast<AllocaInst>(&I))
      Allocas.push_back(AI);
  for (AllocaInst *AI : Allocas)
    AI->moveBefore(NewEntry->end());

  IRBuilder<> Prologue(NewEntry);
  AllocaInst *State = Prologue.CreateAlloca(I32, nullptr, "aegis.state");

  BasicBlock *Dispatch = BasicBlock::Create(Ctx, "aegis.dispatch", &F);
  BasicBlock *Trap = BasicBlock::Create(Ctx, "aegis.trap", &F);
  {
    IRBuilder<> TB(Trap);
    TB.CreateUnreachable();
  }

  SmallVector<BasicBlock *, 32> Cases;
  DenseMap<BasicBlock *, uint32_t> Num;
  for (BasicBlock &BB : F) {
    if (&BB == NewEntry || &BB == Dispatch || &BB == Trap)
      continue;
    Num[&BB] = static_cast<uint32_t>(Cases.size());
    Cases.push_back(&BB);
  }
  if (Cases.empty())
    return false;

  auto Enc = [Key](uint32_t N) { return N ^ Key; };
  auto volatileStoreState = [&](IRBuilder<> &B, Value *V) {
    StoreInst *S = B.CreateStore(V, State, /*isVolatile=*/true);
    S->setVolatile(true);
    B.CreateBr(Dispatch);
  };

  DenseMap<BasicBlock *, BasicBlock *> Trampolines;
  auto trampolineFor = [&](BasicBlock *Succ) -> BasicBlock * {
    auto It = Trampolines.find(Succ);
    if (It != Trampolines.end())
      return It->second;
    BasicBlock *Tr = BasicBlock::Create(Ctx, "aegis.next", &F);
    IRBuilder<> TB(Tr);
    volatileStoreState(TB, ConstantInt::get(I32, Enc(Num[Succ])));
    Trampolines[Succ] = Tr;
    return Tr;
  };

  for (BasicBlock *BB : Cases) {
    Instruction *T = BB->getTerminator();
    if (isa<ReturnInst>(T) || isa<UnreachableInst>(T))
      continue;

    if (auto *BI = dyn_cast<UncondBrInst>(T)) {
      IRBuilder<> B(BI);
      volatileStoreState(B,
                         ConstantInt::get(I32, Enc(Num[BI->getSuccessor(0)])));
      BI->eraseFromParent();
      continue;
    }

    if (auto *BI = dyn_cast<CondBrInst>(T)) {
      IRBuilder<> B(BI);
      Value *Sel = B.CreateSelect(
          BI->getCondition(),
          ConstantInt::get(I32, Enc(Num[BI->getSuccessor(0)])),
          ConstantInt::get(I32, Enc(Num[BI->getSuccessor(1)])), "aegis.next");
      volatileStoreState(B, Sel);
      BI->eraseFromParent();
      continue;
    }

    if (auto *SI = dyn_cast<SwitchInst>(T)) {
      BasicBlock *Default = SI->getDefaultDest();
      SI->setDefaultDest(trampolineFor(Default));
      for (unsigned I = 0; I < SI->getNumCases(); ++I) {
        BasicBlock *Succ = SI->getSuccessor(I + 1);
        SI->setSuccessor(I + 1, trampolineFor(Succ));
      }
      continue;
    }

    std::string Msg = "[aegis-cff] cannot flatten '" + F.getName().str() +
                      "': unsupported terminator";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }

  {
    IRBuilder<> EB(NewEntry);
    volatileStoreState(EB, ConstantInt::get(I32, Enc(Num[&OldEntry])));
  }

  IRBuilder<> DB(Dispatch);
  LoadInst *St = DB.CreateLoad(I32, State, "aegis.state.v");
  St->setVolatile(true);
  LoadInst *Sa = DB.CreateLoad(I32, Salt, "aegis.cff.salt.v");
  Sa->setVolatile(true);
  // salt is zero by construction, so the key is zero at run time; the
  // multiply keeps the dependency visible to the optimizer and analyzer.
  Value *K = DB.CreateMul(Sa, ConstantInt::get(I32, 0x9E3779B9u), "aegis.k");
  Value *Eff = DB.CreateXor(St, K, "aegis.keyed");
  SwitchInst *Sw =
      DB.CreateSwitch(Eff, Trap, static_cast<unsigned>(Cases.size()));
  for (unsigned I = 0; I < Cases.size(); ++I)
    Sw->addCase(ConstantInt::get(cast<IntegerType>(I32), Enc(I)), Cases[I]);

  return true;
}

} // namespace

namespace aegis {

PreservedAnalyses AegisControlFlowPass::run(Module &M,
                                            ModuleAnalysisManager &) {
  const uint32_t Seed = moduleSeed(M);
  const uint32_t Key = controlFlowKey(Seed);
  LLVMContext &Ctx = M.getContext();

  SmallVector<std::string, 4> Unsupported;
  SmallVector<std::string, 4> Ineligible;
  bool AnySelected = false;
  for (const Function &F : M) {
    const int Level = functionLevel(F);
    if (Level < 2)
      continue;
    if (Level > kMaxImplementedLevel) {
      Unsupported.push_back(F.getName().str() + " (level " +
                            std::to_string(Level) + ")");
      continue;
    }
    std::string WhyStorage;
    if (Level >= 3)
      WhyStorage = flatteningIneligibilityReason(F);
    const StringRef Why =
        Level >= 3 ? StringRef(WhyStorage) : ineligibilityReason(F);
    if (!Why.empty()) {
      Ineligible.push_back(F.getName().str() + " (level " +
                           std::to_string(Level) + ": " + Why.str() + ")");
      continue;
    }
    AnySelected = true;
  }

  if (!Unsupported.empty()) {
    for (const std::string &Entry : Unsupported)
      errs() << "[aegis-cff] unsupported: " << Entry << "\n";
    std::string Msg = "[aegis-cff] " + std::to_string(Unsupported.size()) +
                      " function(s) request a level above " +
                      std::to_string(kMaxImplementedLevel) +
                      "; refusing to build a module that claims unimplemented "
                      "protection";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }
  if (!Ineligible.empty()) {
    for (const std::string &Entry : Ineligible)
      errs() << "[aegis-cff] cannot protect: " << Entry << "\n";
    std::string Msg = "[aegis-cff] " + std::to_string(Ineligible.size()) +
                      " selected function(s) cannot be flattened; refusing to "
                      "build unprotectable selections (lower the level or "
                      "change the construct)";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }
  if (!AnySelected) {
    errs() << "[aegis-cff] no level>=2 functions; module unchanged\n";
    return PreservedAnalyses::all();
  }

  GlobalVariable *Guard = M.getNamedGlobal(kGuardGlobalName);
  SmallVector<Function *, 8> DecoyFns;
  for (Function &F : M)
    if (F.getMetadata("aegis.decoy.fn") && !F.isDeclaration())
      DecoyFns.push_back(&F);
  if (!Guard || DecoyFns.empty()) {
    report_fatal_error(
        "[aegis-cff] guard global or decoy functions missing; run "
        "aegis-decoys before aegis-cff",
        /*GenCrashDiag=*/false);
  }

  GlobalVariable *Salt = M.getNamedGlobal(kCffSaltName);
  if (!Salt)
    Salt = new GlobalVariable(
        M, Type::getInt32Ty(Ctx), false, GlobalValue::InternalLinkage,
        ConstantInt::get(Type::getInt32Ty(Ctx), 0), kCffSaltName);

  SmallVector<Metadata *, 8> BogusNames;
  SmallVector<Metadata *, 8> FlattenedNames;
  unsigned BogusFunctions = 0;
  unsigned Flattened = 0;

  for (Function &F : M) {
    const int Level = functionLevel(F);
    if (Level < 2)
      continue;
    if (Level >= 3 ? !eligibleForFlattening(F) : !eligibleForDecoys(F))
      continue;

    injectLiveSplit(F, Guard, Salt);
    const unsigned Edges = injectBogus(F, Salt, DecoyFns, Seed);
    errs() << "[aegis-cff] level=" << Level << " " << F.getName()
           << " bogus_edges=" << Edges << "\n";
    BogusNames.push_back(MDNode::get(Ctx, MDString::get(Ctx, F.getName())));
    ++BogusFunctions;

    if (Level >= 3) {
      if (!flattenFunction(F, Salt, Key))
        report_fatal_error(
            StringRef("[aegis-cff] flattening failed unexpectedly"),
            /*GenCrashDiag=*/false);
      errs() << "[aegis-cff] flattened " << F.getName() << "\n";
      FlattenedNames.push_back(
          MDNode::get(Ctx, MDString::get(Ctx, F.getName())));
      ++Flattened;
    }
  }

  if (!BogusNames.empty())
    M.addModuleFlag(Module::Append, kBogusFlagName,
                    MDNode::get(Ctx, BogusNames));
  if (!FlattenedNames.empty())
    M.addModuleFlag(Module::Append, kFlattenedFlagName,
                    MDNode::get(Ctx, FlattenedNames));

  errs() << "[aegis-cff] summary: seed=" << Seed
         << " level2+=" << BogusFunctions << " flattened=" << Flattened << "\n";
  return PreservedAnalyses::none();
}

} // namespace aegis
