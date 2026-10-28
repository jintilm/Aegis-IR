//===- Policy.cpp - aegis policy JSON parsing and validation --------------===//

#include "aegis/Policy.h"

#include "llvm/ADT/SmallString.h"
#include "llvm/ADT/StringSet.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"

#include <limits>

using namespace llvm;

namespace {

Error makeValidationError(StringRef Path, ArrayRef<std::string> Problems) {
  std::string Msg = ("policy '" + Path + "' has " +
                     std::to_string(Problems.size()) + " problem(s):\n")
                        .str();
  for (const std::string &P : Problems)
    Msg += "  " + P + "\n";
  return createStringError(inconvertibleErrorCode(), Msg);
}

bool isKnownProfile(StringRef Profile) {
  return Profile == "dev" || Profile == "release" || Profile == "research" ||
         Profile == "debug";
}

} // namespace

namespace aegis {

Expected<Policy> parsePolicy(StringRef JSON, StringRef Path) {
  Expected<json::Value> Parsed = json::parse(JSON);
  if (!Parsed)
    return createStringError(inconvertibleErrorCode(),
                             "invalid JSON in '%s': %s", Path.str().c_str(),
                             toString(Parsed.takeError()).c_str());

  const json::Object *Root = Parsed->getAsObject();
  if (!Root)
    return createStringError(inconvertibleErrorCode(),
                             "policy '%s': root must be a JSON object",
                             Path.str().c_str());

  std::vector<std::string> Problems;
  Policy P;

  // schema_version
  if (std::optional<int64_t> V = Root->getInteger("schema_version")) {
    P.SchemaVersion = *V;
    if (*V != 1)
      Problems.push_back("schema_version " + std::to_string(*V) +
                         " is not supported (expected 1)");
  } else {
    Problems.push_back("missing integer 'schema_version'");
  }

  // profile
  if (std::optional<StringRef> S = Root->getString("profile")) {
    P.Profile = S->str();
    if (!isKnownProfile(P.Profile))
      Problems.push_back("profile must be one of dev|release|research|debug, "
                         "got '" +
                         P.Profile + "'");
  } else {
    Problems.push_back("missing string 'profile'");
  }

  // seed (optional)
  if (Root->get("seed")) {
    if (std::optional<int64_t> S = Root->getInteger("seed")) {
      if (*S < 0 || *S > std::numeric_limits<uint32_t>::max())
        Problems.push_back("seed must be in [0, 2^32-1]");
      else
        P.Seed = static_cast<uint32_t>(*S);
    } else {
      Problems.push_back("'seed' must be an integer");
    }
  }

  // functions
  const json::Value *FunctionsValue = Root->get("functions");
  const json::Array *FunctionsArray =
      FunctionsValue ? FunctionsValue->getAsArray() : nullptr;
  if (!FunctionsValue) {
    Problems.push_back("missing array 'functions'");
  } else if (!FunctionsArray) {
    Problems.push_back("'functions' must be an array");
  } else {
    StringSet<> Seen;
    for (size_t I = 0; I < FunctionsArray->size(); ++I) {
      const json::Value &Elem = (*FunctionsArray)[I];
      const json::Object *Obj = Elem.getAsObject();
      std::string Where = "functions[" + std::to_string(I) + "]";
      if (!Obj) {
        Problems.push_back(Where + ": must be an object");
        continue;
      }

      PolicyFunction PF;
      if (std::optional<StringRef> N = Obj->getString("name")) {
        PF.Name = N->str();
        if (PF.Name.empty())
          Problems.push_back(Where + ": 'name' must not be empty");
        else if (!Seen.insert(PF.Name).second)
          Problems.push_back("duplicate policy entry for '" + PF.Name + "'");
      } else {
        Problems.push_back(Where + ": missing string 'name'");
      }

      if (std::optional<int64_t> L = Obj->getInteger("level")) {
        if (*L < 0 || *L > 3)
          Problems.push_back(Where + ": level must be in [0, 3], got " +
                             std::to_string(*L));
        else
          PF.Level = static_cast<int>(*L);
      } else {
        Problems.push_back(Where + ": missing integer 'level'");
      }

      if (std::optional<StringRef> R = Obj->getString("reason"))
        PF.Reason = R->str();

      P.Functions.push_back(std::move(PF));
    }
  }

  // limits (optional)
  if (const json::Value *LimitsValue = Root->get("limits")) {
    const json::Object *LimitsObj = LimitsValue->getAsObject();
    if (!LimitsObj) {
      Problems.push_back("'limits' must be an object");
    } else {
      if (LimitsObj->get("max_binary_growth_percent")) {
        if (std::optional<int64_t> V =
                LimitsObj->getInteger("max_binary_growth_percent")) {
          if (*V < 0)
            Problems.push_back("limits.max_binary_growth_percent must be >= 0");
          else
            P.Limits.MaxBinaryGrowthPercent = *V;
        } else {
          Problems.push_back(
              "limits.max_binary_growth_percent must be an integer");
        }
      }
      if (LimitsObj->get("max_p95_slowdown_percent")) {
        if (std::optional<int64_t> V =
                LimitsObj->getInteger("max_p95_slowdown_percent")) {
          if (*V < 0)
            Problems.push_back("limits.max_p95_slowdown_percent must be >= 0");
          else
            P.Limits.MaxP95SlowdownPercent = *V;
        } else {
          Problems.push_back("limits.max_p95_slowdown_percent must be an "
                             "integer");
        }
      }
    }
  }

  if (!Problems.empty())
    return makeValidationError(Path, Problems);

  return P;
}

Expected<Policy> parsePolicyFile(StringRef Path) {
  ErrorOr<std::unique_ptr<MemoryBuffer>> BufferOrErr =
      MemoryBuffer::getFile(Path);
  if (!BufferOrErr)
    return createStringError(BufferOrErr.getError(),
                             "cannot read policy file '%s'",
                             Path.str().c_str());
  return parsePolicy((*BufferOrErr)->getBuffer(), Path);
}

} // namespace aegis