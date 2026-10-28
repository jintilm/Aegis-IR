# Pinned development container for Aegis-IR.
# Reference environment per docs/dev-environment.md: Ubuntu 24.04 + LLVM 23.
#
# Build:  docker build -t aegis-ir-dev docker/
# Run:    docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      wget ca-certificates lsb-release gnupg software-properties-common \
      build-essential git cmake ninja-build pkg-config \
      python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install LLVM 23 from apt.llvm.org (same procedure as CI; keep in sync).
RUN wget -q https://apt.llvm.org/llvm.sh -O /tmp/llvm.sh \
    && chmod +x /tmp/llvm.sh \
    && /tmp/llvm.sh 23 \
    && apt-get update && apt-get install -y --no-install-recommends \
      clang-23 llvm-23 llvm-23-dev llvm-23-tools clang-format-23 \
    && rm -rf /var/lib/apt/lists/* \
    && rm /tmp/llvm.sh

# Fail the image build early if the toolchain is incomplete.
RUN clang-23 --version \
    && opt-23 --version \
    && llvm-config-23 --version \
    && llvm-config-23 --cmakedir

WORKDIR /src
CMD ["bash"]