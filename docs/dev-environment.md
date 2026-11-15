# Development environment

Status: pinned for the alpha stage. Change requires its own PR plus a full CI
run and a compatibility-matrix update.

## Pinned versions

| Component | Version |
|---|---|
| OS | Ubuntu 24.04 (container, digest-pinned) |
| LLVM / Clang | 23.x from apt.llvm.org |
| CMake | >= 3.20 (distro package) |
| Ninja | distro package |
| C++ standard | C++17 |

Pass-plugin APIs are LLVM-version sensitive. Never mix different major
versions of `clang`, `opt`, `llvm-config` and headers. The container image in
`docker/dev.Dockerfile` is the reference environment; CI installs the same
packages.

The `apt.llvm.org/llvm.sh` installer is pinned by SHA-256 in both the
Dockerfile and CI:

`03878e08f47b66cc95bc4b544b0db3c6d9ce8d60e6cf2492ae357984330a9eae`

The Ubuntu base image is pinned to:

`ubuntu:24.04@sha256:2198e4c65076e9cb0b3d695219df667c0e3b0072da64ca3c2648aca17dcecaf5`

## Using the container

```bash
docker build -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev
```

Inside the container:

```bash
export LLVM_DIR=$(llvm-config-23 --cmakedir)
clang-23 --version && opt-23 --version && llvm-config-23 --version   # record these
cmake -S . -B build -G Ninja -DLLVM_DIR=$LLVM_DIR -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

## Native (non-container) setup

Follow https://apt.llvm.org/ instructions for LLVM 23 packages, then install
`clang-23 llvm-23 llvm-23-dev llvm-23-tools clang-format-23`. Do not add
mismatched distribution repositories; use a supported Ubuntu/Debian base.

## Reproducing the smoke test

```bash
clang++-23 -O0 -S -emit-llvm examples/demo.cpp -o build/demo.ll
opt-23 -load-pass-plugin=build/lib/AegisPass.so -passes=aegis-audit \
  -disable-output build/demo.ll
```

Expected: `[aegis-audit] module: ...` followed by per-function statistics and
a total line; exit code 0; input module unmodified.
