/*
 * Per-call cycle cost of a ROM function, measured on a booted image.
 *
 * usage: table-cost-probe ROM BOOT_FRAMES ITERATIONS kind:label:addr:r0 [...]
 *   kind  s = the function returns a game-text buffer; print it up to the
 *             0xFF terminator (or 48 bytes)
 *         n = the function returns a scalar in r0
 *   addr  even (Thumb) entry address, from arm-none-eabi-nm
 *
 * The probe boots the ROM normally, then hijacks the CPU for each call:
 * Thumb mode, a clean IWRAM stack, r0 = the argument, LR = a sentinel
 * address. It steps one instruction at a time and reports ARM7TDMI cycles
 * from ARMCore::cycles.
 *
 * Interrupts and DMA are disabled and the event scheduler is pushed past the
 * measured window. Without that, GBAProcessEvents fires mid-call and rebases
 * cpu->cycles, which makes short deltas meaningless. mGBA is not a
 * cycle-accurate ARM7TDMI: use the ratios, and re-measure on hardware for a
 * shipping budget.
 *
 * Build (macOS, Homebrew libmgba):
 *   cc -O2 -o table-cost-probe table-cost-probe.c \
 *     -I/opt/homebrew/include -L/opt/homebrew/lib -lmgba
 */
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/arm/isa-inlines.h>

#define SNAPSHOT_MAX 48

static const uint32_t stop = 0x02001000; /* return marker; never executed */
static const uint32_t stackBase = 0x03007E00;

static void quietLogger(struct mLogger *logger, int category, enum mLogLevel level,
                        const char *fmt, va_list args) {
    (void)logger; (void)category; (void)level; (void)fmt; (void)args;
}

static void prepare(struct mCore *core, uint32_t pc, uint32_t arg) {
    struct ARMCore *cpu = core->cpu;
    /* No interrupt and no DMA activity can disturb the measured window. */
    core->busWrite16(core, 0x04000208, 0x0000);
    core->busWrite16(core, 0x040000B8, 0x0000);
    core->busWrite16(core, 0x040000C4, 0x0000);
    core->busWrite16(core, 0x040000D0, 0x0000);
    core->busWrite16(core, 0x040000DC, 0x0000);
    ARMSetPrivilegeMode(cpu, MODE_SYSTEM);
    _ARMSetMode(cpu, MODE_THUMB);
    for (unsigned i = 0; i < 13; ++i)
        cpu->gprs[i] = 0;
    cpu->gprs[0] = arg;
    cpu->gprs[ARM_SP] = stackBase;
    cpu->gprs[ARM_LR] = stop | 1;
    cpu->gprs[ARM_PC] = pc;
    ThumbWritePC(cpu);
    cpu->nextEvent = INT32_MAX;
}

/* Step until control returns to the sentinel; returns the instruction count. */
static unsigned runCall(struct mCore *core) {
    struct ARMCore *cpu = core->cpu;
    for (unsigned steps = 0; steps < 4000000; ++steps) {
        unsigned width = cpu->executionMode == MODE_THUMB ? 2 : 4;
        if ((uint32_t)cpu->gprs[ARM_PC] - width == stop)
            return steps;
        core->step(core);
    }
    return 0;
}

static int parseHex(const char *text, uint32_t *out) {
    if (!text || !*text)
        return 0;
    char *end = NULL;
    unsigned long value = strtoul(text, &end, 16);
    if (!end || *end)
        return 0;
    *out = (uint32_t)value;
    return 1;
}

int main(int argc, char **argv) {
    if (argc < 5)
        return 2;
    const char *romPath = argv[1];
    const unsigned bootFrames = (unsigned)strtoul(argv[2], NULL, 10);
    const unsigned iterations = (unsigned)strtoul(argv[3], NULL, 10);
    if (iterations == 0)
        return 2;

    struct mLogFilter filter;
    mLogFilterInit(&filter);
    filter.defaultLevels = mLOG_FATAL;
    struct mLogger logger = {.log = quietLogger, .filter = &filter};
    mLogSetDefaultLogger(&logger);

    struct mCore *core = mCoreFind(romPath);
    if (!core || !core->init(core))
        return 3;
    mCoreInitConfig(core, "table-cost-probe");
    core->opts.useBios = false;
    core->opts.skipBios = true;
    if (!mCoreLoadFile(core, romPath))
        return 4;
    unsigned w, h;
    core->desiredVideoDimensions(core, &w, &h);
    color_t *pixels = calloc((size_t)w * h, sizeof(*pixels));
    if (!pixels)
        return 5;
    core->setVideoBuffer(core, pixels, w);
    core->reset(core);
    for (unsigned i = 0; i < bootFrames; ++i)
        core->runFrame(core);

    printf("# boot=%u frames iterations=%u\n", bootFrames, iterations);
    for (int i = 4; i < argc; ++i) {
        char spec[256];
        snprintf(spec, sizeof(spec), "%s", argv[i]);
        char *kind = strtok(spec, ":");
        char *label = strtok(NULL, ":");
        char *addrText = strtok(NULL, ":");
        char *argText = strtok(NULL, ":");
        uint32_t addr = 0, arg = 0;
        if (!kind || !label || !parseHex(addrText, &addr) || !parseHex(argText, &arg))
            return 6;

        double total = 0.0;
        unsigned steps = 0, coldSteps = 0, coldCycles = 0;
        for (unsigned n = 0; n < iterations; ++n) {
            prepare(core, addr, arg);
            int32_t before = ((struct ARMCore *)core->cpu)->cycles;
            steps = runCall(core);
            int32_t after = ((struct ARMCore *)core->cpu)->cycles;
            if (steps == 0) {
                fprintf(stderr, "%s: did not return\n", label);
                return 7;
            }
            uint32_t delta = (uint32_t)after - (uint32_t)before;
            if (n == 0) {
                coldSteps = steps;
                coldCycles = delta;
            }
            total += delta;
        }

        /* One more call to snapshot the returned value without timing noise. */
        prepare(core, addr, arg);
        runCall(core);
        struct ARMCore *cpu = core->cpu;
        uint32_t result = (uint32_t)cpu->gprs[0];
        unsigned char snapshot[SNAPSHOT_MAX];
        unsigned length = 0;
        memset(snapshot, 0, sizeof(snapshot));
        if (kind[0] == 's' && ((result >= 0x02000000 && result < 0x03000000) ||
                               (result >= 0x08000000 && result < 0x0A000000))) {
            while (length < SNAPSHOT_MAX) {
                unsigned byte = core->busRead8(core, result + length);
                snapshot[length++] = (unsigned char)byte;
                if (byte == 0xFF)
                    break;
            }
        }
        printf("%s\t%s\t%.1f\t%.1f\t%u\t%u\t%08x\t", kind, label,
               total / (double)iterations, (double)coldCycles, steps, coldSteps, result);
        if (kind[0] == 's') {
            for (unsigned b = 0; b < length; ++b)
                printf("%02x", snapshot[b]);
        } else {
            printf("%u", result);
        }
        printf("\n");
        fflush(stdout);
    }

    mCoreConfigDeinit(&core->config);
    core->deinit(core);
    free(pixels);
    mLogSetDefaultLogger(NULL);
    mLogFilterDeinit(&filter);
    return 0;
}
