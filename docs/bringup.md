# Bring-up log

Facts below are observed on this machine unless marked otherwise.

Host: macOS 27.2 arm64, 10 cores.
Target: GBA, ARM7TDMI, ARMv4T, Thumb-1, `-mabi=apcs-gnu`.
Example ROM: pokeemerald-expansion (ploppoke/pokeemerald-fufufu).

## 2026-11-25

### Toolchain decisions

* The bootstrap LLVM revision is
  `04c4ab8d9a15c548bfd472abd3407bc0be1e137e` (`24.0.0git`). Clang and the
  plugin use the same installation. This build contains the ARM and AArch64
  backends, and ships `clang`, `llvm-ar`, `llvm-config`, and `ld.lld`.
* The ROM build keeps GNU binutils for assembly and linking. The hand-written
  GBA asm uses `.include`/GNU syntax that LLVM's integrated assembler does not
  accept, and pokeemerald's linker script is consumed by GNU `ld`.
* Clang requires UAL syntax in Thumb inline asm: `mov r6, #11` in the old
  dialect is rejected as requiring Thumb-2. The ROM clang path emits `.s`
  into the same GNU assembly pipeline as GCC; the plugin still runs inside
  clang, before assembly.
* `-mthumb-interwork` is a GCC driver flag; clang rejects it. Clang emits
  interworking-safe `bx lr` and the linker handles Thumb/ARM veneers.

### Recipe

Use sibling checkouts of `llvm-project` at the bootstrap revision above,
`picolibc` (1.8.12), `o-mvll` (`gba-port`), `gba-omvll`, and the ROM
repository. The plugin build used Homebrew spdlog 1.17.0, pybind11 3.1.0,
and Python 3.12.

For a fresh checkout, start LLVM at the bootstrap revision, create a local
branch there, and apply `patches/clang-apcs-struct-boundary.patch` with
`git am` as described in the [ABI notes](clang-apcs-layout.md).
Use `o-mvll` at `1ea4da439e` on `gba-port` and the ROM's `omvll` branch.

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
```

`build-llvm.sh` configures the ARM and AArch64 backends and installs clang
and LLD with Ninja. The completed bootstrap install was
`ninja -C "$ROOT/llvm-build" install`. The installed clang compiled a
small Thumb-1 C file; GNU `readelf -A` reported `v4T`, `Thumb-1` and no
unaligned accesses.

### C library and compiler builtins

`build-picolibc.sh` configures Meson with the installed clang and `ld.lld`.
Both C and link arguments use `-mabi=apcs-gnu`; the compile target is
`armv4t-none-eabi`, `-mcpu=arm7tdmi -march=armv4t -mthumb
-mno-unaligned-access`. The build disables multilib, tests, picocrt, TLS,
atomic ungetc, and fast strcmp. It installs to `$PREFIX/picolibc`. Its
`lib/libc.a` contained 1,353 members; GNU `readelf -A` reported only `v4T`,
`Thumb-1` and `Tag_CPU_unaligned_access: None`.

`build-builtins.sh` configures the compiler-rt root as a Generic bare-metal
target with `armv4t-none-eabi` (not `arm-none-eabi`, which selects newer ARM
assembly). It uses Wonderful's GNU `ar`/`ranlib`; Darwin's archive tools
produced an empty archive. The Generic target emits `.obj`
files even with CMake output extension overrides. The install step
re-archives them deterministically as `.o`, in original order, so the
ROM's existing `*.o` linker rules accept them without a layout change.

C compiler-rt code uses APCS-GNU. Its ARM assembly exports EABI aliases
and invokes the weak EABI division-by-zero callbacks. The APCS C build
omits those callbacks, so the script compiles upstream `arm/aeabi_div0.c`
for AAPCS and replaces its otherwise empty member. The installed
`$PREFIX/builtins/libclang_rt.builtins-armv4t.a` contains 143 `.o` members
including `__aeabi_uidiv`, `__udivsi3`, `__aeabi_idiv0`, and `__aeabi_ldiv0`.
GNU `ld` linked a `memcpy`/`snprintf`/division probe through the unchanged
ROM linker script with no undefined symbols.

### O-MVLL

The local `gba-port` commit `1ea4da439e` ports pass registration and the
branch/pass APIs to LLVM 24 and uses X86 backend components only if LLVM
provides them. `build-omvll.sh` configures with
`LLVM_DIR=$PREFIX/lib/cmake/llvm` and writes
`$OMVLL_BUILD/libOMVLL.dylib`. A small Thumb-1 string/arithmetic TU
compiled with the installed clang and assembled with GNU `as`:

```sh
printf '%s\n' 'extern int puts(const char *);' \
  'int probe(int x) { if (x > 3) return puts("arm7tdmi probe") + x; return x ^ 2345; }' |
  OMVLL_CONFIG="$ROOT/gba-omvll/omvll/gba_omvll.py" \
  "$PREFIX/bin/clang" --target=armv4t-none-eabi -mcpu=arm7tdmi -march=armv4t \
    -mthumb -mabi=apcs-gnu -O2 -ffreestanding -fno-addrsig \
    -fpass-plugin="$OMVLL_BUILD/libOMVLL.dylib" -S -x c - -o /tmp/gba-omvll-smoke.s
arm-none-eabi-as -mcpu=arm7tdmi -march=armv4t -meabi=5 \
  -o /tmp/gba-omvll-smoke.o /tmp/gba-omvll-smoke.s
```

The smoke output contained a local decoder but no `.init_array`. Use
local-only string encoding: the ROM's startup code does not run global
constructors. The decoder is generated by the same clang loading the
plugin, not the host system clang.

Control-flow flattening chooses ARM versus Thumb from the function's
`target-features` (with module triple fallback). GNU `objdump` confirmed
Thumb-1 `4900 4708 0011` (`ldr r1,[pc,#0]; bx r1; movs r1,r2`) and ARM
`e51f1004 e12fff11 e1a01002` for both mixed-mode frontend defaults.

Small ARMv4T/Thumb-1 test objects assembled and linked through the ROM
script with arithmetic, opaque constants/fields, local string encoding,
block split/duplication, CFG flattening, function outlining, indirect
calls, break-CFG and function shuffle enabled individually or by the GBA
config. Indirect branch and instruction shuffle also ran and linked, but
their transformations did not change the final object on the probe.
AntiHook only supports AArch64. Assembly/link success is not a runtime
validation of any pass.

### ROM integration (bootstrap clang, before the APCS layout fix)

With the source sweep marker `build/uat/.clang-sweep-running` absent:

```sh
cd "$ROOT/fufufu"
PATH=/opt/wonderful/toolchain/gcc-arm-none-eabi/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  make USE_CLANG=1 rom -j8
```

The Makefile uses `$PREFIX/bin/clang`, `$PREFIX/picolibc`, and
`$PREFIX/builtins/libclang_rt.builtins-armv4t.a`; it still uses GNU `as` and
`ld` and does not change the GCC pipeline's compiler or libraries.
`make` exited 0 in the default `build/emerald` directory; `nm -u
pokeemerald.elf` had no output. The linker used 26,878,644 ROM bytes
(80.10% of 32 MiB), and the padded ROM is 33,554,432 bytes. The linker
warned about the missing `.note.GNU-stack` in `SoftReset.o`; it did not
discard any required compiler-rt symbols. The integration images and
map are preserved as `build/emerald/pokeemerald.unobfuscated.{gba,elf,map}`.

**Not valid for gameplay or save testing.** The integration build
predates the clang APCS record-layout fix. GCC's 32-bit structure size
boundary is not applied by this clang: `SaveBlock1` is 15,496 vs 15,568
bytes, `SaveBlock2` is 3,848 vs 3,884 bytes, a one-`char` struct is 1 vs 4
bytes, and `_Alignof(OamData)` is 2 vs 4. A selected-file obfuscation link
from the same bootstrap clang cannot validate the fixed ABI either.
The installer does not invalidate objects when replacing clang at the
same path; remove `build/emerald/.toolchain-clang` before rebuilding an
existing build directory after a compiler change.

### Patched clang and boot validation

Clang commit `37a0a216311` (LLVM `24.0.0git`) implements GCC-compatible
APCS record alignment and size rounding. The GCC comparison found no
differences across 120 generic and 48 game probes, including
`SaveBlock1` (15,568 bytes), `SaveBlock2` (3,884 bytes), and `OamData`
(alignment 4). Both target libraries were rebuilt with that compiler.

Two runtime bugs were separate from frontend ABI layout:

* `src/agb_flash.c` formerly sized copied Thumb routines by subtracting
  the addresses of adjacent C functions. Clang reordered the functions
  and a stack copy overwrote the IRQ vector. The three helpers now use
  explicit Thumb assembly start/end labels.
* `src/decompress.c` likewise sized stack copies by subtracting C
  function addresses. Clang placed the tANS wrapper before its decoder,
  causing execution of an incomplete ARM routine and rebooting at the
  copyright screen. The four paths now call their ARM decoders directly
  in ROM through the existing interworking wrappers. Tracing showed the
  RFU probe returned normally; enabling or skipping it was not a fix.

Rebuilt after all source fixes in the default `build/emerald` directory:

```sh
cd "$ROOT/fufufu"
rm -f build/emerald/.toolchain-clang
make USE_CLANG=1 rom -j8
for ext in gba elf map; do
    cp "pokeemerald.$ext" "build/emerald/pokeemerald.clang-apcs.$ext"
done
make USE_CLANG=1 OBFUSCATE=1 OBFUSCATE_SRCS='src/random.c src/util.c' rom -j8
for ext in gba elf map; do
    cp "pokeemerald.$ext" "build/emerald/pokeemerald.clang-apcs.obfuscated.$ext"
done
```

| ROM | Used ROM bytes | EWRAM bytes | IWRAM bytes |
| --- | ---: | ---: | ---: |
| Plain | 26,910,488 | 229,184 | 28,356 |
| Selected O-MVLL | 26,916,000 | 229,185 | 28,476 |

Both padded images are 33,554,432 bytes; `arm-none-eabi-nm -u` is empty
for both ELFs. GNU ld warned that `udivmodsi4.S.o` lacks `.note.GNU-stack`.
The obfuscated map loads `random.omvll.o` and `util.omvll.o` only for
those translation units. GNU `nm` finds five local string decoders;
the `BlendPalette` diagnostic is absent from the obfuscated ROM but
present in the plain ROM.

The plain ROM booted to the Pokémon logo at frame 3600 with Homebrew's
headless libmgba 0.10.5 harness (exit 0, no fatal or illegal opcodes):

```sh
/tmp/mgba-gba-boot-smoke build/emerald/pokeemerald.clang-apcs.gba \
    build/emerald/pokeemerald.clang-apcs.boot 3600
```

The log, PNG and savestate are `build/emerald/pokeemerald.clang-apcs.boot.log`
and `build/emerald/pokeemerald.clang-apcs.boot.f3600.{png,ss}`. This
is a boot smoke test, not gameplay or save compatibility validation.

### Clang test suite status

The test C rule shares the clang preprocessing and assembly pipeline
with game C files. The GCC branch is unchanged.
Only the clang test rule passes `-fno-integrated-as`, so event-script
assembly is left for GNU `as`; shipping C flags are unchanged.
The initial run of `make USE_CLANG=1 BUILD_NAME=uatcheck check -j8`
exited 2 before linking or launching Hydra, so no test counts are
available. The first blockers in `/tmp/gba-final-clang-check.log` were:

* `test/mass_outbreak.c:34,63,83,110,121,138`: Clang's inline-asm
  parser rejects `startoutbreak`'s `.if OUTBREAK_COUNT == OUTBREAK_COUNT`
  as not absolute.
* `test/test_runner_battle.c:100,124,148,172`: legacy `add r6, #20` is
  invalid in Thumb-1 unified assembly without the flag-setting `adds`.
* `test/pokemon.c:254` (`givemon respects perfectIVCount`): GNU `as`
  rejects six of clang's Thumb literal loads
  (`build/uatcheck-test/test/pokemon.s:5747–5748,5841,5845,5852,5859`)
  with PC-relative offsets between `0x400` and `0x420`.

**Known limitation:** LLVM 21 and 24 undercount inline-asm macro
expansion when placing a Thumb constant pool in `Test254` at `-O2`.
Both LLVM's assembler and GNU `as` reject the resulting offsets. Only
clang's test `pokemon.o` is compiled at `-O0` to avoid this upstream
bug; neither the shipping ROM nor the compiler is changed.

The rerun compiled `test/pokemon.o` with `-O2 … -O0 -fno-integrated-as`
and passed the previous compilation blockers. Linking initially failed
because `ld_script_test.ld` discarded compiler-rt `.text`. The test
script now selects the archive's `.text`, `.rodata`, `.data`, and `.bss`
alongside the existing libgcc entries; the archive has no COMMON
definitions. Both test ELFs link without undefined symbols.

Hydra ran all 5,900 entries: 5,269 passed, 184 failed, 18 were known
failures, 419 were TODO, 9 were expected failures, and 1 known-failing
test passed unexpectedly. The first failures were `BoxPokemon
encryption works`, the `RandomUniform` mul-vs-mod benchmark, and
`Capture: ball data is properly set in captured pokemon 22/28`.
Log: `/tmp/gba-clang-uatcheck-linked.log`.

The GCC reference used Wonderful GCC with the same picolibc and
compiler-rt archives (`BUILD_NAME=gccref`). Its one failure also occurs
under clang: capture-ball data case `22/28`, `EXPECT_EQ(0, 21)`.

Two fixes reduced the clang failures:

* `include/metaprogram.h`: the null-dereference ternary inside
  `if_comptime` folded to true under clang for dynamic percentages.
  `RandomPercentage` then called `RandomUniform` instead of
  `RandomWeightedArray`. Both ELF files correctly bound all four weak
  RNG aliases to the strong test overrides, and the seeded `Random32`
  streams matched. The predicate now uses `__builtin_constant_p(cond)
  && (cond)`; the dynamic weighted path and constant 50% fast path agree
  under both compilers. The 91 `observed 0.5` failures disappeared.
* `test/pokemon.c`: `BoxPokemon encryption works` allocated a 12-byte
  nickname buffer, but `GetMonData` writes 12 bytes plus the terminator.
  The terminator overwrote the expected-string pointer in the clang
  `-O0` test. The buffer now uses `POKEMON_NAME_LENGTH + 1`; the test
  passes without changing game code or the expected nickname.

| Hydra run (5,900 tests) | Passed | Failed | Known failing | TODO | Expected failing |
| --- | ---: | ---: | ---: | ---: | ---: |
| Wonderful GCC baseline | 5,452 | 1 | 19 | 419 | 9 |
| Clang after predicate fix | 5,430 | 23 | 19 | 419 | 9 |
| Clang after predicate and nickname fixes | 5,431 | 22 | 19 | 419 | 9 |
| Clang after battle and test lifetime fixes | 5,451 | 2 | 19 | 419 | 9 |

The next clang run exposed three independently diagnosed problems:

* `Cmd_waitanimation` passed a null animation argument after a successful
  Cramorant form change. GCC happened to emit animation 61 after reading
  address zero; clang removed that branch because `PlayAnimation` dereferenced
  the null pointer. It now receives a real `u16` zero. Emulator traces matched
  the two compilers' RNG decisions through the first missing animation.
* `CMD_ARGS` views the `gBattleAnimArgs` halfword array as a word-aligned
  APCS struct. The original clang ELF placed the array at `0x02000b2e`;
  a merged ARMv4T word load read wrong arguments and left five animations
  waiting indefinitely. The same parameters stalled with test TUs at `-O0`
  and with a 240-second watchdog instead of 60. Explicitly aligning the
  array moved it to `0x02000b30`; all five animation groups pass.
* The Dynamax test now uses the measured non-Dynamax damage from parameter
  0 instead of reading an uninitialized capture. Two Beat Up tests now
  store captures in objects that survive the return from `SCENE` and
  reset them in `GIVEN`. The RNG and actual HP changes matched GCC.

The final `make USE_CLANG=1 BUILD_NAME=uatcheck check -j8` linked without
undefined symbols and ran all 5,900 tests. `make` exited 2: the shared
capture-ball case still fails, as does the clang-only compile-time
`RandomUniform` performance assertion. No functional clang-only failures
remain in this run. Logs: `/tmp/gba-clang-uatcheck-anim-align.log`
(final), `/tmp/gba-clang-uatcheck-rng-nickname.log` and
`/tmp/gba-clang-uatcheck-rngfix.log` (earlier clang runs), and
`/tmp/gba-gccref-check-isolated.log` (GCC reference).
