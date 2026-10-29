#!/usr/bin/env bash
# Build a release tarball from a clean checkout and write its checksum.
#
# Usage: scripts/package.sh [version]   (default: read from AegisVersion.h)
#
# Output: dist/aegis-ir-<version>-linux-x86_64.tar.gz and dist/SHA256SUMS
#
# The archive contains the pass plugin, public headers, docs and the benchmark
# harness sources. It deliberately does not contain a prebuilt test binary or
# any benchmark answers: the point of the artifact is that a third party can
# rebuild and reproduce, not that they can trust a blob.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(sed -n 's/^#define AEGIS_VERSION_STRING "\(.*\)"$/\1/p' \
  "$REPO_ROOT/include/aegis/AegisVersion.h")}"
IMAGE="${AEGIS_IMAGE:-aegis-ir-dev}"
NAME="aegis-ir-${VERSION}-linux-x86_64"
DIST="$REPO_ROOT/dist"

[ -n "$VERSION" ] || { echo "could not determine version" >&2; exit 1; }

echo "== building $NAME in $IMAGE =="
MSYS_NO_PATHCONV=1 docker run --rm -v "$REPO_ROOT:/src" -w /src "$IMAGE" bash -c '
set -e
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR=/usr/lib/llvm-23/lib/cmake/llvm >/dev/null
cmake --build build -j >/dev/null
cd build && ctest --output-on-failure >/dev/null
echo "build + tests OK"
'

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME"/{plugin,include,docs,tools,tests,benchmarks,scripts}

PLUGIN="$(ls "$REPO_ROOT"/build/lib/*AegisPass.so 2>/dev/null | head -1)"
[ -n "$PLUGIN" ] || { echo "plugin artifact not found in build/lib" >&2; exit 1; }
cp "$PLUGIN" "$STAGE/$NAME/plugin/"
cp -r "$REPO_ROOT/include/aegis" "$STAGE/$NAME/include/"
cp -r "$REPO_ROOT/docs/." "$STAGE/$NAME/docs/"
cp -r "$REPO_ROOT/tools/aegis-bench" "$STAGE/$NAME/tools/"
cp -r "$REPO_ROOT/benchmarks/tasks-public" "$STAGE/$NAME/benchmarks/"
cp -r "$REPO_ROOT/tests" "$STAGE/$NAME/"
cp -r "$REPO_ROOT/scripts" "$STAGE/$NAME/"
cp "$REPO_ROOT/README.md" "$REPO_ROOT/CHANGELOG.md" "$REPO_ROOT/LICENSE" \
   "$REPO_ROOT/SECURITY.md" "$REPO_ROOT/CONTRIBUTING.md" \
   "$STAGE/$NAME/"

# Record what went in, so the archive is self-describing.
{
  echo "version: $VERSION"
  echo "built-from-commit: $(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "built-utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "llvm: 23.x (see docs/dev-environment.md)"
} > "$STAGE/$NAME/BUILD-INFO.txt"

mkdir -p "$DIST"
tar -C "$STAGE" -czf "$DIST/$NAME.tar.gz" "$NAME"
( cd "$DIST" && sha256sum "$NAME.tar.gz" > SHA256SUMS )

echo
echo "artifacts:"
ls -l "$DIST"
cat "$DIST/SHA256SUMS"
