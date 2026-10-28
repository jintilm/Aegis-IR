# Contributing

Thanks for helping. This project makes claims about protection effectiveness;
the contribution rules exist to keep those claims honest.

## Ground rules

1. **No unmeasured claims.** A PR that adds a transform must include a test
   and a stated limitation. README claims require a claims-ledger entry.
2. **Default profile changes need before/after numbers.** Any change to what
   ships in the default profile must attach benchmark or cost-ledger data.
3. **Semantics first.** The default profile must be semantics-preserving.
   Research features live behind explicit opt-in and are off by default.
4. **No deceptive runtime behavior.** PRs implementing sandbox detection that
   changes results, anti-debugging that causes failures, or evasion-oriented
   features will be rejected — see `docs/threat-model.md` §5.
5. **Reproducibility.** Builds must work offline; no network calls at build
   time; no LLM API keys in the pipeline.

## Workflow

```bash
docker build -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev

export LLVM_DIR=$(llvm-config-23 --cmakedir)
cmake -S . -B build -G Ninja -DLLVM_DIR=$LLVM_DIR -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
clang++-23 -O0 -S -emit-llvm examples/demo.cpp -o build/demo.ll
opt-23 -load-pass-plugin=build/lib/AegisPass.so -passes=aegis-audit \
  -disable-output build/demo.ll
clang-format-23 --dry-run -Werror lib/*.cpp include/aegis/*.h
```

One PR solves one reviewable problem. Commit messages: `feat:`, `fix:`,
`test:`, `docs:`, `build:`, `chore:`.

## Research feature admission (one-page proposal required)

State: which asset and which attacker class it targets; what assumption is new
versus existing techniques; where it fails; measured runtime/compat cost; how
pre/post semantics are proven equal; whether it changes behavior under
analysis; how it is disabled and rolled back; how third parties reproduce it.