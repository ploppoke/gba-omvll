#!/usr/bin/env python3
"""Compare ARM ELF layout constants and initialized bitfields without running target code."""
import argparse
import itertools
import pathlib
import re
import struct
import subprocess
import tempfile

WORKSPACE = pathlib.Path(__file__).resolve().parents[2]
LLVM = WORKSPACE / 'toolchain/llvm'
DEFAULT_GCC_PREFIX = pathlib.Path('/opt/wonderful/toolchain/gcc-arm-none-eabi')
FLAGS = ['-mcpu=arm7tdmi', '-march=armv4t', '-mthumb', '-std=gnu17', '-ffreestanding']
GENERIC = r'''
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
struct Char { char c; };
struct Mixed { char c; short s; char t; };
union Union { char c; short s; };
struct Nested { char c; struct Char n; struct Mixed m[2]; char t; };
struct Packed { char c; short s; char t; } __attribute__((packed));
struct PackedAligned { char c; short s; } __attribute__((packed, aligned(2)));
struct Aligned { char c; } __attribute__((aligned(8)));
struct Align2 { char c; } __attribute__((aligned(2)));
struct AlignedFields { char c; u8 x:3 __attribute__((aligned(2))); char t; };
struct PackedMember { char c; short s __attribute__((packed)); char t; };
#pragma pack(push, 1)
struct PragmaChar1 { char c; };
struct PragmaPack1 { char c; short s; char t; };
struct PragmaZero32 { char c; u32 :0; char t; };
#pragma pack(pop)
#pragma pack(push, 2)
struct PragmaChar2 { char c; };
struct PragmaBits2 { u8 a:7, b:6; char t; };
struct PragmaPack2 { char c; int i; char t; };
#pragma pack(pop)
struct Bits8 { u8 a:7, b:6; char t; };
struct Bits16 { u8 a:7; u16 b:11; char t; };
struct Bits32 { u16 a:15; u32 b:21; char t; };
struct Bits64 { u32 a:31; u64 b:34; char t; };
struct AnonBits { u32 :1; char t; };
struct NamedBits { u32 a:1; char t; };
struct AnonWide { u8 a:7; u16 :11; char t; };
struct PackedBitMember { u8 a:7; u16 b:11 __attribute__((packed)); char t; };
union UnionBits { u32 a:7; u16 b:11; };
union UnionZero { u16 :0; u8 a:3; };
struct Zero8 { u8 a:1; u8 :0; char t; };
struct Zero16 { u8 a:1; u16 :0; char t; };
struct Zero32 { u8 a:1; u32 :0; char t; };
struct Zero64 { u8 a:1; u64 :0; char t; };
struct LeadingZero { u32 :0; char t; };
struct TrailingZero { char c; u32 :0; };
struct ExplicitZero { char c; u16 :0 __attribute__((aligned(8))); char t; };
struct PackedZero { u8 a:1; u32 :0; char t; } __attribute__((packed));
struct PackedBits { u8 a:7; u32 b:29; char t; } __attribute__((packed));
struct Flex { char c; char data[]; };
struct Empty {};
struct Char stride_char[2] = {{1},{2}};
struct Packed stride_packed[2] = {{1,2,3},{4,5,6}};
struct Aligned stride_aligned[2] = {{1},{2}};
'''
GAME = r'''
#include "global.h"
#include "main.h"
#include "battle.h"
#include "pokemon.h"
'''
GENERIC_TYPES = re.findall(r'^(struct|union) (\w+) \{', GENERIC, re.M)
GAME_TYPES = [('struct', tag) for tag in '''SaveBlock1 SaveBlock2 Main OamData Sprite
    Pokeblock Pokemon BoxPokemon PokemonSubstruct0 PokemonSubstruct3 ItemSlot
    Bag ObjectEvent BerryTree SecretBase BattlePokemon BattleStruct SpeciesInfo'''.split()]
GENERIC_OFFSETS = {
    'Mixed': 's t', 'Nested': 'n m t', 'Packed': 's t', 'PackedAligned': 's',
    'AlignedFields': 't', 'PackedMember': 's t', 'PragmaPack1': 's t',
    'PragmaBits2': 't', 'NamedBits': 't', 'AnonWide': 't', 'PackedBitMember': 't',
    'PragmaPack2': 'i t', 'PragmaZero32': 't', 'Bits8': 't', 'Bits16': 't',
    'Bits32': 't', 'Bits64': 't', 'AnonBits': 't', 'Zero8': 't', 'Zero16': 't',
    'Zero32': 't', 'Zero64': 't', 'LeadingZero': 't', 'PackedZero': 't',
    'PackedBits': 't', 'Flex': 'data',
    'ExplicitZero': 't',
}
GAME_OFFSETS = {
    'SaveBlock1': 'bag pcItems pokeblocks berryBlenderRecords playerRoomDecorations',
    'Main': 'oamBuffer state', 'OamData': 'affineParam',
}
GENERIC_BITS = [
    (f'struct {tag}', 'b') for tag in ('Bits8', 'Bits16', 'Bits32', 'Bits64',
                                     'PackedBits', 'PragmaBits2', 'PackedBitMember')
] + [('union UnionBits', 'b'), ('struct AlignedFields', 'x')]
GAME_BITS = [('struct OamData', tag) for tag in ('y', 'x', 'tileNum', 'paletteNum')]


def probe_source(game):
    source = GAME if game else GENERIC
    types = GAME_TYPES if game else GENERIC_TYPES
    offsets = GAME_OFFSETS if game else GENERIC_OFFSETS
    bits = GAME_BITS if game else GENERIC_BITS
    measures = [(f'{op}({kind} {tag})', f'{op}({kind} {tag})')
                for kind, tag in types for op in ('sizeof', '_Alignof')]
    measures += [(f'offsetof({tag}.{field})', f'__builtin_offsetof(struct {tag}, {field})')
                 for tag, fields in offsets.items() for field in fields.split()]
    if not game:
        measures += [(f'sizeof({v})', f'sizeof({v})')
                     for v in ('stride_char', 'stride_packed', 'stride_aligned')]
    source += '\nconst unsigned values[] __attribute__((section(".probe"))) = {\n'
    source += ''.join(f'    {expr},\n' for _, expr in measures) + '};\n'
    for i, (ty, field) in enumerate(bits):
        source += (f'const {ty} bits{i} __attribute__((section(".bit{i}"))) '
                   f'= {{ .{field} = 1 }};\n')
    return source, [label for label, _ in measures], bits


def run(cc, objcopy, flags, directory, source, labels, bits, verbose):
    obj = directory / 'probe.o'
    result = subprocess.run([cc, *FLAGS, *flags, '-x', 'c', '-c', '-o', obj, '-'],
                            input=source, text=True, capture_output=True)
    if result.returncode or verbose:
        print(result.stderr, end='')
    result.check_returncode()
    sections = [('.probe', directory / 'values')]
    sections += [(f'.bit{i}', directory / f'bit{i}') for i in range(len(bits))]
    dumps = itertools.chain.from_iterable(('--dump-section', f'{name}={file}')
                                          for name, file in sections)
    subprocess.run([objcopy, *dumps, obj], check=True)
    raw = sections[0][1].read_bytes()
    values = dict(zip(labels, struct.unpack(f'<{len(labels)}I', raw), strict=True))
    for (ty, field), (_, file) in zip(bits, sections[1:], strict=True):
        mask = int.from_bytes(file.read_bytes(), 'little')
        assert mask.bit_count() == 1, (ty, field, mask)
        values[f'bitoff({ty}.{field})'] = mask.bit_length() - 1
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clang', default=LLVM / 'bin/clang')
    parser.add_argument('--gcc-prefix', type=pathlib.Path, default=DEFAULT_GCC_PREFIX,
                        help='ARM GCC installation (including arm-none-eabi-objcopy)')
    parser.add_argument('--game', action='store_true')
    parser.add_argument('--game-dir', type=pathlib.Path, default=WORKSPACE / 'fufufu')
    parser.add_argument('--game-version', default='EMERALD')
    parser.add_argument('--libc-include', type=pathlib.Path, default=LLVM / 'picolibc/include')
    parser.add_argument('--abi', choices=('apcs-gnu', 'aapcs'), action='append',
                        help='limit comparisons to this ABI (repeatable)')
    parser.add_argument('--gcc-matrix', action='store_true', help='show GCC values for each ABI and boundary')
    parser.add_argument('--explicit', action='store_true', help='also compare explicit 8/32/64-bit boundaries')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    cc = args.gcc_prefix / 'bin/arm-none-eabi-gcc'
    objcopy = args.gcc_prefix / 'bin/arm-none-eabi-objcopy'
    source, labels, bits = probe_source(args.game)
    common = ['-nostdinc']
    gcc_extra = []
    clang_extra = ['--target=armv4t-none-eabi']
    if args.game:
        common += ['-iquote', args.game_dir / 'include', '-isystem', args.libc_include,
                   '-DMODERN=1', '-DTESTING=0', f'-D{args.game_version}']
        gcc_extra += ['-isystem', subprocess.check_output([cc, '-print-file-name=include'], text=True).strip()]
        clang_extra += ['-isystem', pathlib.Path(subprocess.check_output([args.clang, '-print-resource-dir'],
                                   text=True).strip()) / 'include']
    scenarios = [(abi, boundary) for abi in (args.abi or ('apcs-gnu', 'aapcs'))
                 for boundary in ((None, 8, 32, 64) if args.gcc_matrix or args.explicit else (None,))]
    results = {}
    failures = 0
    with tempfile.TemporaryDirectory(prefix='gba-apcs-') as temp:
        tmp = pathlib.Path(temp)
        for abi, boundary in scenarios:
            flags = [*common, f'-mabi={abi}']
            if boundary is not None:
                flags.append(f'-mstructure-size-boundary={boundary}')
            if args.game and abi == 'aapcs':
                # This game's enum bit-fields require full-sized enums; bare
                # metal GCC's AAPCS default uses short enums and rejects them.
                flags.append('-fno-short-enums')
            gcc = run(cc, objcopy, [*gcc_extra, *flags], tmp, source, labels, bits, args.verbose)
            name = f'{abi}:{boundary or "default"}'
            if args.gcc_matrix:
                results[name] = gcc
                continue
            clang = run(args.clang, objcopy, [*clang_extra, *flags], tmp, source, labels, bits, args.verbose)
            diff = {label: (gcc[label], clang[label]) for label in gcc if gcc[label] != clang[label]}
            print(f'{name}: {len(diff)} differences / {len(gcc)} checked')
            for label, (g, c) in diff.items():
                print(f'  {label}: GCC {g:#x}, clang {c:#x}')
            failures += len(diff)
    if results:
        print(f'{"probe":37}' + ''.join(f' {name:>16}' for name in results))
        for label in next(iter(results.values())):
            print(f'{label:37}' + ''.join(f' {values[label]:16}' for values in results.values()))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
