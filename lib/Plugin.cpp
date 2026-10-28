//===- Plugin.cpp - pass plugin registration ------------------------------===//
//
// Single registration point for every pass in the AegisPass shared library.
// Only ONE translation unit may define llvmGetPassPluginInfo; registering
// passes from multiple TUs silently drops all but one on most platforms.
//
// Pipeline syntax notes (LLVM 20+):
//   - pass parameters are encoded inside the pass name: `aegis-policy<key=val>`
//     (the pre-20 `pass(key=val)` Key/Val form was removed);
//   - the third callback argument is the nested *pipeline*, not parameters.
//
//===----------------------------------------------------------------------===//

#include "AegisAuditPass.h"
#include "AegisPolicyPass.h"
#include "aegis/AegisVersion.h"

#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Passes/PassBuilder.h"
// LLVM 20+ moved PassPlugin.h from llvm/Passes/ to llvm/Plugins/.
#if __has_include("llvm/Plugins/PassPlugin.h")
#include "llvm/Plugins/PassPlugin.h"
#else
#include "llvm/Passes/PassPlugin.h"
#endif
#include "llvm/Support/raw_ostream.h"

#include <string>

using namespace llvm;

extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "AegisPass", AEGIS_VERSION_STRING,
          [](PassBuilder &PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager &MPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name == "aegis-audit") {
                    MPM.addPass(aegis::AegisAuditPass());
                    return true;
                  }
                  if (PassBuilder::checkParametrizedPassName(Name,
                                                             "aegis-policy")) {
                    std::string PolicyPath;
                    StringRef Params = Name;
                    Params.consume_front("aegis-policy");
                    if (!Params.empty()) {
                      // "<key=val,key=val>"
                      Params = Params.drop_front(1).drop_back(1);
                      SmallVector<StringRef, 4> Pairs;
                      Params.split(Pairs, ',');
                      for (StringRef Pair : Pairs) {
                        auto [Key, Val] = Pair.split('=');
                        if (Key.trim() == "policy")
                          PolicyPath = Val.trim().str();
                      }
                    }
                    if (PolicyPath.empty()) {
                      errs() << "[aegis-policy] missing policy file; use "
                                "-passes='aegis-policy<policy=FILE>'\n";
                      return false;
                    }
                    MPM.addPass(aegis::AegisPolicyPass(std::move(PolicyPath)));
                    return true;
                  }
                  return false;
                });
          }};
}