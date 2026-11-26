# gba-omvll

O-MVLL (LLVM IR obfuscator) ported to the Game Boy Advance:
ARM7TDMI / ARMv4T, Thumb-1, bare metal, no OS.

Reference target: [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion)
(ploppoke/pokeemerald-fufufu), a ~400-TU C/asm GBA ROM built with a modern
toolchain.

## Why a port is needed

O-MVLL is an LLVM pass plugin, so it inherits LLVM's ARM backend, but its
assumptions come from Android/iOS:

* it is built against one exact LLVM release, loaded into the matching clang;
* its JIT (used at compile time to synthesize helpers) links the host;
* generated code assumes a hosted C runtime (libc, sometimes TLS/`dlopen`);
* its ARM support was written for ARMv7-A/AArch64 Android/iOS, not ARMv4T.

GBA adds constraints the upstream project never targets: 16-bit Thumb-1
encodings only (no Thumb-2), `-mabi=apcs-gnu` to interwork with the existing
GNU-built ROM, no dynamic loader, no threads, and a 32 MiB address space.

## Toolchain

The LLVM compiler and target libraries are built from source. The ROM uses
Wonderful's GNU binutils for assembly and linking.

| Component | Role |
| --- | --- |
| LLVM / clang 24.0.0git | compiler; ARM backend with ARMv4T/Thumb-1 support |
| lld | ELF linker available to clang (binutils `ld` still used for the ROM) |
| [picolibc](https://github.com/picolibc/picolibc) | freestanding C library built for Thumb-1 with `-mabi=apcs-gnu` |
| compiler-rt builtins | ARMv4T compiler runtime; replaces libgcc |
| [o-mvll](https://github.com/open-obfuscator/o-mvll) (ploppoke fork) | pass plugin, patched for LLVM main + GBA |
| GNU binutils (`arm-none-eabi-as`/`ld`) | assembles hand-written ROM asm and links the ROM |

## Layout

```
scripts/build-llvm.sh        LLVM main -> $PREFIX
scripts/build-picolibc.sh    picolibc -> $PREFIX/picolibc
scripts/build-builtins.sh    compiler-rt -> $PREFIX/builtins
scripts/build-omvll.sh       o-mvll plugin -> $OMVLL_BUILD/libOMVLL.dylib
picolibc/armv4t-cross.ini    meson cross file (arm7tdmi, Thumb-1, apcs-gnu)
omvll/omvll.yml              plugin discovery file
omvll/gba_omvll.py           per-function/per-module obfuscation policy
patches/                     minimal diffs carried by the forks
```

## Build

Use sibling checkouts of `llvm-project`, picolibc 1.8.12, the `gba-port`
branch of [ploppoke/o-mvll](https://github.com/ploppoke/o-mvll), `gba-omvll`,
and the `omvll` branch of [ploppoke/pokeemerald-fufufu](https://github.com/ploppoke/pokeemerald-fufufu).
Start LLVM from `04c4ab8d9a15c548bfd472abd3407bc0be1e137e` and apply the
[APCS record-layout patch](patches/clang-apcs-struct-boundary.patch).
The verified LLVM checkout was `37a0a216311`; see the
[ABI validation](docs/clang-apcs-layout.md). Build the plugin against the
same LLVM prefix that will load it.

```sh
export ROOT="$HOME/decomp/poke"
export PREFIX="$ROOT/toolchain/llvm"
export OMVLL_BUILD="$ROOT/omvll-build"
export PATH="/opt/wonderful/toolchain/gcc-arm-none-eabi/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$ROOT/gba-omvll"
bash scripts/build-llvm.sh
bash scripts/build-picolibc.sh
bash scripts/build-builtins.sh
bash scripts/build-omvll.sh
cd "$ROOT/fufufu"
make USE_CLANG=1 rom -j8
```

To obfuscate `random.c` and `util.c` only, preserve the plain outputs before
running `make USE_CLANG=1 OBFUSCATE=1 OBFUSCATE_SRCS='src/random.c src/util.c' rom -j8`.
The [bring-up log](docs/bringup.md) includes dependencies, known limitations,
and the exact release artifact paths.

## Use

Compile a translation unit for the GBA with the plugin loaded:

```sh
OMVLL_CONFIG="$ROOT/gba-omvll/omvll/gba_omvll.py" \
  "$PREFIX/bin/clang" --target=armv4t-none-eabi -mcpu=arm7tdmi -march=armv4t \
    -mthumb -mabi=apcs-gnu -O2 -fno-addrsig \
    -fpass-plugin="$OMVLL_BUILD/libOMVLL.dylib" \
    -S src/foo.c -o foo.s
arm-none-eabi-as -mcpu=arm7tdmi -march=armv4t -meabi=5 -o foo.o foo.s
```

## Status

The final plain and selected O-MVLL builds link without undefined symbols.
The link uses **26,910,488** ROM bytes plain and **26,916,000** obfuscated;
both padded images are 33,554,432 bytes. The plain ROM reaches the Pokémon
logo at frame 3600 in headless mGBA 0.10.5 with no fatal error. The PNG is
`build/emerald/pokeemerald.clang-apcs.boot.f3600.png` in the ROM checkout.
This is a boot smoke test, not gameplay or save validation.

The port uses Thumb-1 UAL assembly, GCC-compatible APCS record layout,
bounded Thumb flash helpers, and direct calls to the ARM decompressors
in ROM. It also fixes the compile-time RNG predicate, the null form-change
animation argument, and animation argument alignment.

| Hydra run (5,900 tests) | Passed | Failed | Known failing | TODO | Expected failing |
| --- | ---: | ---: | ---: | ---: | ---: |
| Wonderful GCC reference | 5,452 | 1 | 19 | 419 | 9 |
| Patched clang | 5,451 | 2 | 19 | 419 | 9 |

Both fail capture-ball data case `22/28`; clang also fails the compile-time
`RandomUniform` performance assertion. The clang test rule delegates inline
assembly to GNU `as`, and the test linker admits compiler-rt sections.
Only test `pokemon.o` uses `-O0` to avoid an LLVM Thumb literal-pool bug;
the shipping flags are unchanged.
