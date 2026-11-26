"""O-MVLL policy for ARM7TDMI / Thumb-1 bare metal.

Only IR-level passes that do not assume a hosted runtime are enabled.
Passes that emit architecture-specific trampolines are opt-in per function
until they are validated on Thumb-1 (see docs/bringup.md).
"""
import omvll
from functools import lru_cache

# preproc puts COMPOUND_STRING arrays in these mergeable ROM sections.
omvll.config.local_byte_array_sections = [".rodata.compound_string."]
# Place local string decode buffers in EWRAM (.sbss) so IWRAM stack headroom is untouched.
omvll.config.local_decode_section = ".sbss"
# Compile-time in-place encryption for the four major Pokémon data tables.
# Offsets and element strides match ARMv4T APCS-GNU layout in pokeemerald-fufufu.
omvll.config.encrypt_tables = [
    {
        "name": "gSpeciesInfo",
        "stride": 264,
        "seed": 0x5A3C9E17,
        "ring_section": ".sbss",
        "fields": [
            {"kind": "scalar", "offset": 0, "size": 1, "key": 0x11A3B5C7},  # baseHP
            {"kind": "scalar", "offset": 1, "size": 1, "key": 0x22B4C6D9},  # baseAttack
            {"kind": "scalar", "offset": 2, "size": 1, "key": 0x33C5D7EB},  # baseDefense
            {"kind": "scalar", "offset": 3, "size": 1, "key": 0x44D6E8FD},  # baseSpeed
            {"kind": "scalar", "offset": 4, "size": 1, "key": 0x55E7F90F},  # baseSpAttack
            {"kind": "scalar", "offset": 5, "size": 1, "key": 0x66F80A21},  # baseSpDefense
            {"kind": "inline_string", "offset": 31, "size": 13, "slots": 8, "key": 0x77091B33},  # categoryName
            {"kind": "inline_string", "offset": 44, "size": 13, "slots": 8, "key": 0x881A2C45},  # speciesName
            {"kind": "scalar", "offset": 62, "size": 2, "key": 0x992B3D57},  # height
            {"kind": "scalar", "offset": 64, "size": 2, "key": 0xAA3C4E69},  # weight
            {
                "kind": "pointer_string",
                "offset": 76,
                "size": 256,
                "slots": 4,
                "key": 0xBB4D5F7B,
                "extra_strings": ["gFallbackPokedexText"],
            },  # description
        ],
    },
    {
        "name": "gAbilitiesInfo",
        "stride": 28,
        "seed": 0x6B4DAF29,
        "ring_section": ".sbss",
        "fields": [
            {"kind": "inline_string", "offset": 0, "size": 17, "slots": 8, "key": 0x13579BDF},  # name
            {"kind": "pointer_string", "offset": 20, "size": 160, "slots": 4, "key": 0x2468ACE1},  # description
        ],
    },
    {
        "name": "gMovesInfo",
        "stride": 64,
        "seed": 0x7C5EC03B,
        "ring_section": ".sbss",
        "fields": [
            {"kind": "pointer_string", "offset": 0, "size": 32, "slots": 8, "key": 0x3579BDF3},  # name
            {
                "kind": "pointer_string",
                "offset": 4,
                "size": 160,
                "slots": 4,
                "key": 0x468ACE05,
                "extra_strings": ["gNotDoneYetDescription"],
            },  # description
        ],
    },
    {
        "name": "gItemsInfo",
        "stride": 48,
        "seed": 0x8D6FD14D,
        "ring_section": ".sbss",
        "fields": [
            {"kind": "scalar", "offset": 0, "size": 4, "key": 0x579BDF17},  # price
            {"kind": "pointer_string", "offset": 12, "size": 160, "slots": 4, "key": 0x68ACE029},  # description
            {
                "kind": "pointer_string",
                "offset": 20,
                "size": 32,
                "slots": 8,
                "key": 0x79BDF13B,
                "extra_strings": ["gQuestionMarksItemName"],
            },  # name
            {"kind": "pointer_string", "offset": 24, "size": 32, "slots": 8, "key": 0x8ACE024D},  # pluralName
            {"kind": "scalar", "offset": 34, "size": 1, "key": 0x9BDF135F},  # flingPower
        ],
    },
]

TABLE_MODULES = (
    "pokemon.c",
    "pokemon.i",
    "move.c",
    "move.i",
    "item.c",
    "item.i",
)

TABLE_OBF_PREFIXES = (
    "GetSpecies",
    "IsSpeciesEnabled",
    "SanitizeSpeciesId",
    "GetAbility",
    "GetMove",
    "SanitizeMoveId",
    "GetItem",
    "CopyItemName",
    "DoesItemHavePluralName",
    "SanitizeItemId",
    "__omvll_decode_",
)

# Functions that must stay untouched: startup/interrupt paths and anything
# already written in inline asm.
EXCLUDED = {
    "AgbMain",
    "IntrMain",
}


class GBAConfig(omvll.ObfuscationConfig):
    def obfuscate_string(self, mod: omvll.Module, func: omvll.Function,
                         string: bytes):
        if func.name in EXCLUDED or mod.name.endswith(TABLE_MODULES):
            return None
        # module constructor that would decode globals at startup does not
        # exist on this target. Local mode decodes at each use site.
        return omvll.StringEncOptLocal()

    def obfuscate_constants(self, mod: omvll.Module, func: omvll.Function):
        if func.name in EXCLUDED:
            return None
        if mod.name.endswith(TABLE_MODULES):
            if not func.name.startswith(TABLE_OBF_PREFIXES):
                return None
        return omvll.OpaqueConstantsBool(True)

    def obfuscate_arithmetic(self, mod: omvll.Module, func: omvll.Function):
        if func.name in EXCLUDED:
            return None
        if mod.name.endswith(TABLE_MODULES):
            if not func.name.startswith(TABLE_OBF_PREFIXES):
                return None
        return omvll.ArithmeticOpt(2)

    def basic_block_split(self, mod: omvll.Module, func: omvll.Function):
        if func.name in EXCLUDED:
            return None
        if mod.name.endswith(TABLE_MODULES):
            return None
        return omvll.BasicBlockSplitWithProbability(20)


@lru_cache(maxsize=1)
def omvll_get_config() -> omvll.ObfuscationConfig:
    return GBAConfig()
