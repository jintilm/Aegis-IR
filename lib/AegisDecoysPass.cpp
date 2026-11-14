//===- AegisDecoysPass.cpp - Tier-1 decoy injection -----------------------===//
//
// What this pass guarantees:
//   * semantics: decoy branches are dynamically dead by construction (the
//     guard global is zero-initialised with internal linkage and never stored
//     to, so the volatile load always yields 0);
//   * survival: decoy functions have external linkage and `noinline`, decoy
//     strings are referenced from their bodies, so -O2 / GlobalDCE keep them;
//   * determinism: every artifact derives from the module seed, so the same
//     policy seed reproduces the same module.
//
// What it does not do: hide that decoys exist. Tier-1 honesty — the verifier
// and benchmark treat the reported decoy list as ground truth.
//
//===----------------------------------------------------------------------===//

#include "AegisDecoysPass.h"
#include "DecoyCorpus.h"

#include "llvm/IR/Constants.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/MDBuilder.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Transforms/Utils/BasicBlockUtils.h"

#include <string>

using namespace llvm;

namespace {

Function *createDecoyFunction(Module &M, StringRef Name, StringRef Text) {
  LLVMContext &Ctx = M.getContext();
  Type *I8Ptr = PointerType::getUnqual(Ctx);
  FunctionType *FT = FunctionType::get(Type::getInt1Ty(Ctx),
                                       {I8Ptr, Type::getInt64Ty(Ctx)}, false);
  Function *F = Function::Create(FT, GlobalValue::ExternalLinkage, Name, &M);
  F->addFnAttr(Attribute::NoInline);
  F->addFnAttr(Attribute::NoUnwind);
  F->addFnAttr(Attribute::Cold);
  F->setMetadata("aegis.decoy.fn", MDNode::get(Ctx, {}));

  // Curated string, referenced from the body so it survives GlobalDCE.
  Constant *StrConst = ConstantDataArray::getString(Ctx, Text, false);
  auto *StrGV = new GlobalVariable(M, StrConst->getType(), true,
                                   GlobalValue::PrivateLinkage, StrConst);
  StrGV->setUnnamedAddr(GlobalValue::UnnamedAddr::Global);
  StrGV->setMetadata("aegis.decoy.str", MDNode::get(Ctx, {}));

  BasicBlock *Entry = BasicBlock::Create(Ctx, "entry", F);
  BasicBlock *Head = BasicBlock::Create(Ctx, "loop", F);
  BasicBlock *LoopBody = BasicBlock::Create(Ctx, "loop.body", F);
  BasicBlock *Done = BasicBlock::Create(Ctx, "done", F);

  IRBuilder<> B(Entry);
  Value *Data = F->getArg(0);
  Value *Len = F->getArg(1);
  Value *Cap = B.CreateAnd(Len, ConstantInt::get(Type::getInt64Ty(Ctx), 63));
  Value *StrPtr =
      B.CreateInBoundsGEP(StrGV->getValueType(), StrGV,
                          {B.getInt64(0), B.getInt64(0)}, "decoy.str");
  B.CreateBr(Head);

  B.SetInsertPoint(Head);
  PHINode *Idx = B.CreatePHI(Type::getInt64Ty(Ctx), 2, "i");
  PHINode *Hash = B.CreatePHI(Type::getInt64Ty(Ctx), 2, "h");
  Idx->addIncoming(B.getInt64(0), Entry);
  Hash->addIncoming(B.getInt64(0xcbf29ce484222325ULL), Entry);
  Value *More = B.CreateICmpULT(Idx, Cap);
  B.CreateCondBr(More, LoopBody, Done);

  B.SetInsertPoint(LoopBody);
  Value *Ptr = B.CreateInBoundsGEP(Type::getInt8Ty(Ctx), Data, Idx);
  Value *Ch = B.CreateLoad(Type::getInt8Ty(Ctx), Ptr);
  Value *Chz = B.CreateZExt(Ch, Type::getInt64Ty(Ctx));
  Value *Mixed = B.CreateXor(Hash, Chz);
  Value *HashNext = B.CreateMul(
      Mixed, ConstantInt::get(Type::getInt64Ty(Ctx), 1099511628211ULL));
  Value *IdxNext = B.CreateAdd(Idx, B.getInt64(1));
  Idx->addIncoming(IdxNext, LoopBody);
  Hash->addIncoming(HashNext, LoopBody);
  B.CreateBr(Head);

  B.SetInsertPoint(Done);
  // Volatile: a plain load of the first char of a constant string is folded
  // away by -O2, which then lets GlobalDCE delete the string. The decoy
  // string must survive, so the read is made opaque to the optimizer.
  LoadInst *First = B.CreateLoad(Type::getInt8Ty(Ctx), StrPtr, "decoy.ch");
  First->setVolatile(true);
  Value *Firstz = B.CreateZExt(First, Type::getInt64Ty(Ctx));
  Value *Result = B.CreateICmpEQ(Hash, Firstz);
  B.CreateRet(Result);
  return F;
}

bool injectGuard(Function &F, GlobalVariable *Guard,
                 ArrayRef<Function *> DecoyFns, uint32_t Seed) {
  LLVMContext &Ctx = F.getContext();
  BasicBlock &Entry = F.getEntryBlock();

  // Split the entry block after allocas and PHIs: the guard test and decoy
  // branch live in the (new) entry, the original body moves to a fresh block.
  // SplitBlock rewrites successors' PHI predecessor lists for us — doing this
  // by hand leaves dangling %entry references and breaks the module verifier.
  auto SplitPt = Entry.begin();
  while (SplitPt != Entry.end() &&
         (isa<PHINode>(SplitPt) || isa<AllocaInst>(SplitPt)))
    ++SplitPt;
  if (SplitPt == Entry.end())
    return false;
  BasicBlock *Body = SplitBlock(&Entry, SplitPt);

  // Dynamically-dead decoy block with plausible calls.
  // Keep the cold arm out of the entry-to-body fallthrough path. Placing it
  // before Body forces the normal path to jump over it, which is measurable on
  // small hot functions even though the guard is perfectly predictable.
  BasicBlock *Decoy = BasicBlock::Create(Ctx, "aegis.decoy", &F);
  {
    IRBuilder<> DB(Decoy);
    const unsigned Calls = 1 + (Seed % 2);
    for (unsigned K = 0; K < Calls; ++K) {
      Function *DF = DecoyFns[(Seed + K) % DecoyFns.size()];
      DB.CreateCall(DF, {ConstantPointerNull::get(PointerType::getUnqual(Ctx)),
                         ConstantInt::get(Type::getInt64Ty(Ctx), 0)});
    }
    DB.CreateUnreachable();
  }

  // Guard terminator: volatile read of a never-written zero. SplitBlock left
  // an unconditional branch to the body here; it is replaced below.
  Entry.getTerminator()->eraseFromParent();
  IRBuilder<> EB(&Entry);
  LoadInst *G = EB.CreateLoad(Type::getInt32Ty(Ctx), Guard, "aegis.g");
  G->setVolatile(true);
  Value *Cmp =
      EB.CreateICmpNE(G, ConstantInt::get(Type::getInt32Ty(Ctx), 0), "aegis.c");
  auto *Branch = EB.CreateCondBr(Cmp, Decoy, Body);
  // Keep the dead arm out of the hot placement path. The volatile wait-free
  // load remains the semantic guard; this metadata only guides block layout.
  MDBuilder MDB(Ctx);
  Branch->setMetadata(LLVMContext::MD_prof,
                      MDB.createBranchWeights(1, 1000000));
  return true;
}

} // namespace

namespace aegis {

PreservedAnalyses AegisDecoysPass::run(Module &M, ModuleAnalysisManager &) {
  const uint32_t Seed = moduleSeed(M);
  const DecoyPlan Plan = buildDecoyPlan(Seed);
  LLVMContext &Ctx = M.getContext();

  // Nothing selected by the policy: leave the module untouched rather than
  // decorating it with decoys that guard nothing.
  bool AnySelected = false;
  SmallVector<std::string, 4> Unsupported;
  SmallVector<std::string, 4> Skipped;
  for (const Function &F : M) {
    const int Level = functionLevel(F);
    if (Level < 1)
      continue;
    if (Level > kMaxImplementedLevel) {
      Unsupported.push_back(F.getName().str() + " (level " +
                            std::to_string(Level) + ")");
      continue;
    }
    const StringRef Why = ineligibilityReason(F);
    if (!Why.empty()) {
      Skipped.push_back(F.getName().str() + " (" + Why.str() + ")");
      continue;
    }
    AnySelected = true;
  }
  // Accepting a higher tier without implementing it would ship a module whose
  // policy claims protection that no transform applied.
  if (!Unsupported.empty()) {
    for (const std::string &Entry : Unsupported)
      errs() << "[aegis-decoys] unsupported: " << Entry << "\n";
    std::string Msg = "[aegis-decoys] " + std::to_string(Unsupported.size()) +
                      " function(s) request a protection level above " +
                      std::to_string(kMaxImplementedLevel) +
                      "; refusing to build a module that claims unimplemented "
                      "protection (lower the policy level or use a release "
                      "that implements it)";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }
  // A selected function the transform cannot touch is the same class of lie:
  // the policy says protected, the binary is not.
  if (!Skipped.empty()) {
    for (const std::string &Entry : Skipped)
      errs() << "[aegis-decoys] cannot protect: " << Entry << "\n";
    std::string Msg = "[aegis-decoys] " + std::to_string(Skipped.size()) +
                      " selected function(s) cannot be transformed; refusing "
                      "to build unprotectable selections (drop them from the "
                      "policy or build from IR without -O0/optnone)";
    report_fatal_error(StringRef(Msg), /*GenCrashDiag=*/false);
  }
  if (!AnySelected) {
    errs() << "[aegis-decoys] no selected functions; module unchanged\n";
    return PreservedAnalyses::all();
  }

  GlobalVariable *Guard = M.getNamedGlobal(kGuardGlobalName);
  if (!Guard)
    Guard = new GlobalVariable(
        M, Type::getInt32Ty(Ctx), false, GlobalValue::InternalLinkage,
        ConstantInt::get(Type::getInt32Ty(Ctx), 0), kGuardGlobalName);

  // Decoy functions (external linkage; kept by the optimizer).
  SmallVector<Function *, 8> DecoyFns;
  for (size_t I = 0; I < Plan.FunctionNames.size(); ++I) {
    std::string Final = Plan.FunctionNames[I];
    unsigned Suffix = 0;
    while (M.getNamedValue(Final))
      Final = Plan.FunctionNames[I] + "_v" + std::to_string(++Suffix);
    Function *F = createDecoyFunction(M, Final, Plan.Strings[I]);
    errs() << "[aegis-decoys] decoy fn=" << Final << " str=\""
           << Plan.Strings[I] << "\"\n";
    DecoyFns.push_back(F);
  }

  // Guard every policy-selected function.
  unsigned Guarded = 0;
  SmallVector<Metadata *, 8> GuardedNames;
  for (Function &F : M) {
    if (functionLevel(F) < 1 || !eligibleForDecoys(F))
      continue;
    if (injectGuard(F, Guard, DecoyFns, Seed)) {
      errs() << "[aegis-decoys] guarded " << F.getName() << "\n";
      GuardedNames.push_back(MDNode::get(Ctx, MDString::get(Ctx, F.getName())));
      ++Guarded;
    }
  }

  // Record what we guarded. After inlining the attribute may be gone, but the
  // module flag survives, so the verifier can tell "erased" from "not
  // selected".
  if (!GuardedNames.empty())
    M.addModuleFlag(Module::Append, kGuardedFlagName,
                    MDNode::get(Ctx, GuardedNames));

  errs() << "[aegis-decoys] summary: seed=" << Seed << " guarded=" << Guarded
         << " decoy_functions=" << DecoyFns.size()
         << " decoy_strings=" << DecoyFns.size() << "\n";
  return PreservedAnalyses::none();
}

} // namespace aegis
