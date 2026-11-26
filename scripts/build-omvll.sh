#!/usr/bin/env bash
# Build the O-MVLL pass plugin against the LLVM built by build-llvm.sh.
set -euo pipefail

ROOT=${ROOT:-$HOME/decomp/poke}
PREFIX=${PREFIX:-$ROOT/toolchain/llvm}
SRC=${OMVLL_SRC:-$ROOT/o-mvll}
BUILD=${OMVLL_BUILD:-$ROOT/omvll-build}
JOBS=${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}

test -d "$PREFIX/lib/cmake/llvm" || { echo "missing LLVM cmake package under $PREFIX" >&2; exit 1; }

PYTHON=${PYTHON:-$(brew --prefix python@3.12)/bin/python3.12}
SPDLOG_DIR=${SPDLOG_DIR:-$(brew --prefix spdlog)/lib/cmake/spdlog}
PYBIND11_DIR=${PYBIND11_DIR:-$(brew --prefix pybind11)/share/cmake/pybind11}

cmake -G Ninja -S "$SRC/src" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR="$PREFIX/lib/cmake/llvm" \
  -Dspdlog_DIR="$SPDLOG_DIR" \
  -Dpybind11_DIR="$PYBIND11_DIR" \
  -DPython3_EXECUTABLE="$PYTHON"

ninja -C "$BUILD" -j "$JOBS" OMVLL
ls -l "$BUILD/libOMVLL.dylib" 2>/dev/null || ls -l "$BUILD"/libOMVLL.*
