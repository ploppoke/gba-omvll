#!/usr/bin/env bash
# Build LLVM/clang/lld from upstream main for the GBA port.
# Host compiler: Apple clang (bootstrap). Target backends: ARM + AArch64.
set -euo pipefail

ROOT=${ROOT:-$HOME/decomp/poke}
SRC=${LLVM_SRC:-$ROOT/llvm-project}
BUILD=${LLVM_BUILD:-$ROOT/llvm-build}
PREFIX=${PREFIX:-$ROOT/toolchain/llvm}
JOBS=${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}

cmake -G Ninja -S "$SRC/llvm" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_PROJECTS="clang;lld" \
  -DLLVM_TARGETS_TO_BUILD="ARM;AArch64" \
  -DLLVM_ENABLE_ASSERTIONS=OFF \
  -DLLVM_INCLUDE_TESTS=OFF \
  -DLLVM_INCLUDE_EXAMPLES=OFF \
  -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DLLVM_INCLUDE_DOCS=OFF \
  -DLLVM_ENABLE_BINDINGS=OFF \
  -DCMAKE_INSTALL_PREFIX="$PREFIX"

ninja -C "$BUILD" -j "$JOBS" install
"$PREFIX/bin/clang" --version
