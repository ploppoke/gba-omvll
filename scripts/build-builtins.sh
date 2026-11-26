#!/usr/bin/env bash
# Build compiler-rt builtins for ARMv4T with the clang built by build-llvm.sh.
# These replace GCC's libgcc (__aeabi_*, 64-bit integer, soft-float helpers).
set -euo pipefail

ROOT=${ROOT:-$HOME/decomp/poke}
PREFIX=${PREFIX:-$ROOT/toolchain/llvm}
SRC=${LLVM_SRC:-$ROOT/llvm-project}
BUILD=${BUILTINS_BUILD:-$ROOT/builtins-build}
CLANG=${CLANG:-$PREFIX/bin/clang}
BINUTILS=${BINUTILS:-/opt/wonderful/toolchain/gcc-arm-none-eabi/bin}
AR=$BINUTILS/arm-none-eabi-ar
RANLIB=$BINUTILS/arm-none-eabi-ranlib
JOBS=${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}

TARGET_FLAGS=(--target=armv4t-none-eabi -mcpu=arm7tdmi -march=armv4t)
test -x "$CLANG" || { echo "missing $CLANG (run build-llvm.sh first)" >&2; exit 1; }
test -x "$AR" && test -x "$RANLIB" || { echo "missing ARM ar/ranlib in $BINUTILS" >&2; exit 1; }

cmake -G Ninja -S "$SRC/compiler-rt" -B "$BUILD" \
  -DCMAKE_C_COMPILER="$CLANG" \
  -DCMAKE_ASM_COMPILER="$CLANG" \
  -DCMAKE_AR="$AR" \
  -DCMAKE_RANLIB="$RANLIB" \
  -DCMAKE_C_COMPILER_TARGET=armv4t-none-eabi \
  -DCMAKE_ASM_COMPILER_TARGET=armv4t-none-eabi \
  -DCMAKE_SYSTEM_NAME=Generic \
  -DCMAKE_C_FLAGS="${TARGET_FLAGS[*]} -mthumb -mabi=apcs-gnu -fno-pic" \
  -DCMAKE_ASM_FLAGS="${TARGET_FLAGS[*]}" \
  -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
  -DCMAKE_BUILD_TYPE=Release \
  -DCOMPILER_RT_BUILD_BUILTINS=ON \
  -DCOMPILER_RT_BUILD_SANITIZERS=OFF \
  -DCOMPILER_RT_BUILD_XRAY=OFF \
  -DCOMPILER_RT_BUILD_LIBFUZZER=OFF \
  -DCOMPILER_RT_BUILD_PROFILE=OFF \
  -DCOMPILER_RT_BUILD_MEMPROF=OFF \
  -DCOMPILER_RT_BUILD_ORC=OFF \
  -DCOMPILER_RT_BAREMETAL_BUILD=ON \
  -DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON

ninja -C "$BUILD" -j "$JOBS"

ARCHIVE="$BUILD/lib/generic/libclang_rt.builtins-armv4t.a"
MEMBERS=$("$AR" t "$ARCHIVE")
test -n "$MEMBERS" || { echo "empty $ARCHIVE" >&2; exit 1; }

# CMake Generic emits .obj members, which the ROM's *.o linker rules discard.
# Retain the original member order and write a deterministic GNU archive.
mkdir -p "$PREFIX/builtins"
STAGE=$(mktemp -d "$PREFIX/builtins/.archive.XXXXXXXX")
trap 'rm -rf "$STAGE"' EXIT
NAME=$(basename "$ARCHIVE")
"$AR" x --output="$STAGE" "$ARCHIVE"
OBJECTS=()
while IFS= read -r member; do
  case "$member" in
    *.obj) name="${member%.obj}.o"; mv "$STAGE/$member" "$STAGE/$name"; member="$name" ;;
  esac
  OBJECTS+=("$STAGE/$member")
done <<< "$MEMBERS"

# ARM assembly exports EABI aliases and calls the EABI division-by-zero
# hooks, which upstream compiles out of the APCS C build.
"$CLANG" "${TARGET_FLAGS[@]}" -mthumb -mabi=aapcs -ffreestanding -O2 -c \
  "$SRC/compiler-rt/lib/builtins/arm/aeabi_div0.c" -o "$STAGE/aeabi_div0.c.o"
"$AR" crD "$STAGE/$NAME" "${OBJECTS[@]}"
"$RANLIB" -D "$STAGE/$NAME"
mv "$STAGE/$NAME" "$PREFIX/builtins/$NAME"
ls -l "$PREFIX/builtins/$NAME"
