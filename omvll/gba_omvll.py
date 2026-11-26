"""O-MVLL policy for ARM7TDMI / Thumb-1 bare metal.

Only IR-level passes that do not assume a hosted runtime are enabled.
Passes that emit architecture-specific trampolines are opt-in per function
until they are validated on Thumb-1 (see docs/bringup.md).
"""
import omvll
from functools import lru_cache

# Functions that must stay untouched: startup/interrupt paths and anything
# already written in inline asm.
EXCLUDED = {
    "AgbMain",
    "IntrMain",
}

class GBAConfig(omvll.ObfuscationConfig):
    def obfuscate_string(self, mod: omvll.Module, func: omvll.Function,
                         string: bytes):
        if func.name in EXCLUDED:
            return None
        # No global mode: pokeemerald's crt0 never runs .init_array, so the
        # module constructor that would decode globals at startup does not
        # exist on this target. Local mode decodes at each use site.
        return omvll.StringEncOptLocal()

    def obfuscate_constants(self, mod: omvll.Module, func: omvll.Function):
        if func.name in EXCLUDED:
            return None
        return omvll.OpaqueConstantsBool(True)

    def obfuscate_arithmetic(self, mod: omvll.Module, func: omvll.Function):
        if func.name in EXCLUDED:
            return None
        return omvll.ArithmeticOpt(2)

    def basic_block_split(self, mod: omvll.Module, func: omvll.Function):
        if func.name in EXCLUDED:
            return None
        return omvll.BasicBlockSplitWithProbability(20)


@lru_cache(maxsize=1)
def omvll_get_config() -> omvll.ObfuscationConfig:
    return GBAConfig()
