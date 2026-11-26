#!/usr/bin/env bash
# Build picolibc for the GBA using the clang built by build-llvm.sh.
set -euo pipefail

ROOT=${ROOT:-$HOME/decomp/poke}
PREFIX=${PREFIX:-$ROOT/toolchain/llvm}
SRC=${PICOLIBC_SRC:-$ROOT/picolibc}
BUILD=${PICOLIBC_BUILD:-$ROOT/picolibc-build}
CLANG=${CLANG:-$PREFIX/bin/clang}
JOBS=${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}

test -x "$CLANG" || { echo "missing $CLANG (run build-llvm.sh first)" >&2; exit 1; }

CROSS=$(mktemp -t gba-cross.XXXXXX.ini)
trap 'rm -f "$CROSS"' EXIT
sed -e "s|@CLANG@|$CLANG|g" -e "s|@LLVM_BIN@|$PREFIX/bin|g" \
  "$ROOT/gba-omvll/picolibc/armv4t-cross.ini" > "$CROSS"

SETUP_ARGS=(
  --prefix "$PREFIX/picolibc"
  --buildtype release
  -Dmultilib=false
  -Dtests=false
  -Dpicocrt=false
  -Dnewlib-global-errno=true
  -Dthread-local-storage=false
  -Dio-long-long=false
  -Dformat-default=integer
)

if [ -d "$BUILD" ]; then
  meson setup --reconfigure "$BUILD" "$SRC" --cross-file "$CROSS" "${SETUP_ARGS[@]}"
else
  meson setup "$BUILD" "$SRC" --cross-file "$CROSS" "${SETUP_ARGS[@]}"
fi

ninja -C "$BUILD" -j "$JOBS" install
