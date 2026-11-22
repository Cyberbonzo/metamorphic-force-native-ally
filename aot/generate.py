"""Translate the Metamorphic Force 68000 program ROM to position-independent x86-64.

The board maps 2 MB of program ROM at 0x000000-0x1fffff: chips 01/02 interleaved
at 0x000000 and chips 03/04 interleaved at 0x100000. For every even ROM PC emit a
native entry containing its extension operands as an immediate, followed by a
direct branch to precompiled instruction semantics. All decoding happens here.
Computed guest jumps use PC-to-code arithmetic. The Z80 sound program is not
translated; it runs on the FBNeo Z80 core. The generated files derive from the
owner's ROM and stay private to their build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

ROM_SIZE = 0x200000
# FBNeo keeps 68000 memory byte-swapped on little-endian hosts, so the chip it
# loads at offset +0 (01, 03) carries the low byte of each big-endian word.
BANKS = (  # (offset, high-byte CRC, low-byte CRC, chip size)
    (0x000000, 0x04ED41DF, 0x12515518, 0x40000),  # 224aaa02.15f, 224aaa01.15h
    (0x100000, 0xADA53BA4, 0xA5BEDB01, 0x80000),  # 224a04, 224a03
)
SLOT_SIZE = 16
VENEER_SIZE = 8


def read_program(path):
    required = {crc for _, even, odd, _ in BANKS for crc in (even, odd)}
    chips = {}
    for item in path.iterdir():
        if item.is_file() and item.stat().st_size in (0x40000, 0x80000):
            data = item.read_bytes()
            crc = zlib.crc32(data)
            if crc in required:
                chips[crc] = data
    image = bytearray(ROM_SIZE)
    for offset, even, odd, size in BANKS:
        for lane, crc in enumerate((even, odd)):
            if crc not in chips or len(chips[crc]) != size:
                raise ValueError(f"Missing or incorrect program ROM {crc:08x}")
            image[offset + lane:offset + 2 * size:2] = chips[crc]
    return bytes(image)


def widen_screen_bounds(program, margin):
    """Move the playfield limits the game applies to screen X by the margin.

    The routines compare the object's screen X at (8,A0) unsigned, after
    folding negative values to the left limit. In 16:9 the left limit becomes
    negative, so the patched code compares signed instead. Every patch keeps
    the instruction length; the original bytes are checked first.
    """
    if margin == 0:
        return program
    code = bytearray(program)

    def imm(value):
        return (value & 0xffff).to_bytes(2, "big").hex()

    # Players (routine at 0x058b80) were kept within screen X [0x20, 0xf4]. The
    # new limits are [0x20 - m, 0xf4 + margin], where m = min(margin, camera)
    # and the camera X is the word at 0x202824: at the start of a stage, left
    # of the level is empty map, so the player stops where the arcade did.
    # The longer routine lives in the unused 0x080000-0x0fffff ROM window,
    # which the translator covers like the rest of the program space.
    left_limit = (                          # d1 = 0x20 - min(margin, max(camera, 0))
        "30390020 2824"                     # move.w  $202824.l,d0  (camera X)
        "0c40" + imm(margin) +              # cmpi.w  #margin,d0
        "6f04"                              # ble.s   +4
        "303c" + imm(margin) +              # move.w  #margin,d0
        "4a40" "6c02" "7000"                # tst.w d0; bge.s +2; moveq #0,d0
        "323c0020" "9240"                   # move.w #$20,d1; sub.w d0,d1
    )
    right_limit = imm(0xf4 + margin)
    clamp = 0x0F0000
    clamp_routine = (
        "48e7c000"                          # movem.l d0-d1,-(a7)
        + left_limit +
        "b2680008" "6d08"                   # cmp.w (8,a0),d1; blt.s +8
        "31410008" "42680012"               # move.w d1,(8,a0); clr.w ($12,a0)
        "0c68" + right_limit + "0008"       # cmpi.w #right,(8,a0)
        "6f0a"                              # ble.s +10
        "317c" + right_limit + "0008"       # move.w #right,(8,a0)
        "42680012"                          # clr.w   ($12,a0)
        "4cdf0003"                          # movem.l (a7)+,d0-d1
        "4e75"                              # rts
    )
    # A player state (0x05d8c8) ends when the player meets either limit. The
    # test returns Z=1 while the player is strictly between the current limits.
    inside = 0x0F0100
    inside_routine = (
        "48e7c000"                          # movem.l d0-d1,-(a7)
        + left_limit +
        "30280008" "b041"                   # move.w (8,a0),d0; cmp.w d1,d0
        "6f0e"                              # ble.s  outside
        "0c40" + right_limit +              # cmpi.w #right,d0
        "6c08"                              # bge.s  outside
        "7000" "4cdf0003" "4e75"            # moveq #0,d0 (Z=1); restore; rts
        "7001" "4cdf0003" "4e75"            # outside: moveq #1,d0 (Z=0); restore; rts
    )
    for address, routine in ((clamp, clamp_routine), (inside, inside_routine)):
        routine = bytes.fromhex(routine.replace(" ", ""))
        if any(code[address:address + len(routine)]):
            raise ValueError("Helper area is not empty")
        code[address:address + len(routine)] = routine

    def jsr(address):
        return "4eb9" + address.to_bytes(4, "big").hex()

    # Horizontal tilemap streaming (0x0117c6, 0x011858): whenever a layer's X
    # crosses 32 pixels the game copies the one 32-pixel block 384 pixels ahead
    # of it into the 512-pixel ring, so the ring holds [x - 96, x + 416). After
    # the camera turns back by more than 48 pixels (boss arenas) the extra left
    # columns would show blocks of the far right. Each call now also copies the
    # two blocks just left of the layer's X; their ring slots lie outside the
    # ahead window, so nothing the game needs is overwritten. Positions below
    # 64 are skipped: there is no map left of the stage origin.
    streams = []
    for entry, wrapper in ((0x0117c6, 0x0F0200), (0x011858, 0x0F0300)):
        body = entry + 6                                  # after lea $300000,a0
        again = ("41f900300000" + jsr(body)               # lea $300000,a0; jsr body
                 + "4cd70610")                            # movem.l (a7),d4/a1-a2
        routine = ("48e70860"                             # movem.l d4/a1-a2,-(a7)
                   + again
                   + "0c440040" "6d24"                    # cmpi.w #64,d4; blt.s done
                   + "044401c0" + again                   # subi.w #448,d4 -> block at x-64
                   + "044401a0" + "41f900300000" + jsr(body)  # subi.w #416,d4 -> block at x-32
                   + "4cdf0610" "4e75")                   # done: movem.l (a7)+,...; rts
        routine = bytes.fromhex(routine)
        if any(code[wrapper:wrapper + len(routine)]):
            raise ValueError("Helper area is not empty")
        code[wrapper:wrapper + len(routine)] = routine
        streams.append((entry, "41f900300000", "4ef9" + wrapper.to_bytes(4, "big").hex()))

    # The forest arenas (segment tables at 0x010b34 and 0x0111fc) stop tile
    # streaming: their camera range fits the ring for a 288-pixel screen. They
    # keep streaming like the preceding segments (0x010ca8, same map), so the
    # wider screen does not show blocks from beyond the arena.
    arena_tables = [(0x010b42 + 4 * segment, "00010d3c", "00010ca8") for segment in (15, 16)]
    arena_tables += [(0x01120a + 4 * segment, "00010d3c", "00010ca8") for segment in (5, 6)]

    patches = streams + arena_tables + [
        # tst.w (8,a0); bpl -> jsr clamp; bra.s 0x058bb8 (the Y limits)
        (0x058b80, "4a6800086a00000a", jsr(clamp) + "6030"),
        # Player at an edge: bits in 0x202b8a/0x202b8b at X <= 0x30 / >= 0xf0.
        (0x058c24, "6b00000c", "4e714e71"),                 # bmi -> nop nop
        (0x058c28, "0c6800300008", "0c68" + imm(0x30 - margin) + "0008"),
        (0x058c2e, "6200000c", "6e00000c"),                 # bhi -> bgt
        (0x058c3c, "0c6800f00008", "0c68" + imm(0xf0 + margin) + "0008"),
        (0x058c42, "65000008", "6d000008"),                 # bcs -> blt
        # Two player states wait while X is outside (0, 0x114), which the old
        # limits never allowed; with the wider limits the player would stay
        # frozen at the right edge.
        (0x05d818, "0c6800000008", "0c68" + imm(-margin) + "0008"),
        (0x05d81e, "6300005a", "6f00005a"),                 # bls -> ble
        (0x05d822, "0c6801140008", "0c68" + imm(0x114 + margin) + "0008"),
        (0x05d828, "64000050", "6c000050"),                 # bcc -> bge
        (0x05d992, "0c6800000008", "0c68" + imm(-margin) + "0008"),
        (0x05d998, "63000026", "6f000026"),                 # bls -> ble
        (0x05d99c, "0c6801140008", "0c68" + imm(0x114 + margin) + "0008"),
        (0x05d9a2, "6400001c", "6c00001c"),                 # bcc -> bge
        # cmpi/bls/cmpi/bcc against [0x20, 0xf4] -> jsr inside; beq.s rts; bra.s on
        (0x05d8d6, "0c68002000086300000e0c6800f4000864000004",
         jsr(inside) + "670c" "600c" + "4e71" * 5),
        # 0x070ae0: other actors. Screen X limited to [0x10, 0x110].
        (0x070aea, "6b00000c", "4e714e71"),                 # bmi -> nop nop
        (0x070aee, "0c6800100008", "0c68" + imm(0x10 - margin) + "0008"),
        (0x070af4, "64000028", "6c000028"),                 # bcc -> bge
        (0x070b12, "317c00100008", "317c" + imm(0x10 - margin) + "0008"),
        (0x070b1e, "0c6801100008", "0c68" + imm(0x110 + margin) + "0008"),
        (0x070b24, "63000026", "6f000026"),                 # bls -> ble
        (0x070b42, "317c01100008", "317c" + imm(0x110 + margin) + "0008"),
        # 0x070b52: other actors. Screen X limited to [0x20, 0x100].
        (0x070b5c, "6b00000c", "4e714e71"),                 # bmi -> nop nop
        (0x070b60, "0c6800200008", "0c68" + imm(0x20 - margin) + "0008"),
        (0x070b66, "6200000e", "6e00000e"),                 # bhi -> bgt
        (0x070b6a, "317c00200008", "317c" + imm(0x20 - margin) + "0008"),
        (0x070b76, "0c6801000008", "0c68" + imm(0x100 + margin) + "0008"),
        (0x070b7c, "6500000c", "6d00000c"),                 # bcs -> blt
        (0x070b80, "317c01000008", "317c" + imm(0x100 + margin) + "0008"),
    ]
    for address, before, after in patches:
        before, after = bytes.fromhex(before), bytes.fromhex(after)
        if len(before) != len(after) or code[address:address + len(before)] != before:
            raise ValueError(f"Unexpected program bytes at {address:06x}")
        code[address:address + len(after)] = after
    return bytes(code)


def decode_table(source):
    bodies = dict(re.findall(r"^static void (m68k_op_\w+)\(void\)\n\{\n(.*?)^\}", source, re.M | re.S))
    table = [("m68k_op_illegal", 0)] * 65536
    rows = re.findall(r"\{(m68k_op_\w+)\s*,\s*(0x\w+),\s*(0x\w+),\s*\{\s*(\d+),", source)
    if len(rows) < 1000 or len(bodies) < 1000:
        raise ValueError("Could not identify Musashi semantics and decode masks")
    for name, mask, match, cycles in rows:
        mask, match = int(mask, 16), int(match, 16)
        free = 0xffff ^ mask
        bits = free
        while True:
            table[match | bits] = (name, int(cycles))
            if bits == 0:
                break
            bits = (bits - 1) & free
    return bodies, table


def write_sites(image, ops, out):
    veneers = {opcode: i for i, opcode in enumerate(ops)}
    words = [w for (w,) in struct.iter_unpack(">H", image)]
    veneer_base = len(words) * SLOT_SIZE
    padded = words + [0] * 4
    native = bytearray(len(words) * SLOT_SIZE)
    for i, opcode in enumerate(words):
        at = i * SLOT_SIZE
        ext = sum(padded[i+1+k] << (16*k) for k in range(4))
        dest = veneer_base + veneers[opcode] * VENEER_SIZE
        # movabs $extension_words,%rdi ; jmp rel32 ; nop
        struct.pack_into("<2sQBiB", native, at, b"\x48\xbf", ext, 0xe9, dest - (at + 15), 0x90)
    blob = out / "sites_main.bin"
    blob.write_bytes(native)
    assembly = [".text", ".p2align 4", ".globl mforce_sites_main", ".hidden mforce_sites_main",
                "mforce_sites_main:", f'.incbin "{blob.resolve().as_posix()}"']
    for opcode in ops:
        assembly += [".byte 0xe9", f".long mforce_op_{opcode:04x} - . - 4", ".byte 0x90,0x90,0x90"]
    assembly.append('.section .note.GNU-stack,"",@progbits')
    (out / "sites.S").write_text("\n".join(assembly) + "\n")


def generate_header(cpu, out):
    source = (cpu / "m68kcpu.h").read_text()
    begin = source.index("INLINE uint m68ki_read_imm_16(void)\n{")
    end = source.index("\n}", source.index("INLINE uint m68ki_read_imm_32(void)\n{", begin)) + 2
    literal_reads = """
static uint64_t mforce_literals;
INLINE uint m68ki_read_imm_16(void)
{
    /* Each native site carries all four possible 68000 extension words. */
    unsigned int shift = (REG_PC - REG_PPC - 2u) * 8u;
    if (shift >= 64u) abort();
    REG_PC += 2;
    return (uint)(mforce_literals >> shift) & 65535u;
}
INLINE uint m68ki_read_imm_32(void)
{
    uint hi = m68ki_read_imm_16();
    return (hi << 16) | m68ki_read_imm_16();
}
"""
    header = (source[:begin] + "#ifdef MFORCE_COMPILED_KERNEL\n" + literal_reads + "\n#else\n"
              + source[begin:end] + "\n#endif\n" + source[end:])
    (out / "m68kcpu.h").write_text(header)


def generate_core(cpu, table, out):
    core = (cpu / "m68kcpu.c").read_text()
    marker = '#include "m68kfpu.c"'
    extra = """
#include <stdio.h>
#include <stdlib.h>
extern const unsigned char mforce_sites_main[];
unsigned char m68ki_cycles[4][65536];
static const unsigned char mforce_cycles[65536] = {
#include "cycles.inc"
};
void m68ki_build_opcode_table(void)
{
    memcpy(m68ki_cycles[0], mforce_cycles, sizeof(mforce_cycles));
}
static void mforce_run_site(void)
{
    unsigned pc = REG_PC & 0xffffff;
    if (pc >= 0x200000 || (pc & 1)) {
        fprintf(stderr,"Metamorphic Force: no compiled code for PC %06x (previous PC %06x)\\n",pc,REG_PPC);
        abort();
    }
    ((void (*)(void))(mforce_sites_main + ((size_t)pc << 3)))();
}
"""
    old = "REG_IR = m68ki_read_imm_16();\n\t\t\tm68ki_instruction_jump_table[REG_IR]();\n\t\t\tUSE_CYCLES(CYC_INSTRUCTION[REG_IR]);"
    if core.count(old) != 2:
        raise ValueError("Unexpected 68000 execute loop")
    core = core.replace(marker, marker + "\n" + extra).replace(old, "mforce_run_site();")
    (out / "m68kcpu.c").write_text(core)
    (out / "cycles.inc").write_text("\n".join(",".join(str(c) for _, c in table[i:i+64]) + "," for i in range(0, 65536, 64)))


def write_kernels(ops, bodies, table, out):
    preamble = """#include <stdint.h>
#include <stdlib.h>
#define MFORCE_COMPILED_KERNEL
#include "m68kcpu.h"
extern void m68040_fpu_op0(void);
extern void m68040_fpu_op1(void);
"""
    for batch in range(64):
        chunks = [preamble]
        for opcode in ops[batch::64]:
            name, cycles = table[opcode]
            body = re.sub(r"\breturn\s*;", "goto complete;", bodies[name])
            chunks += [f"#undef REG_IR\n#define REG_IR 0x{opcode:04x}u",
                       f"void mforce_op_{opcode:04x}(uint64_t operands)\n{{",
                       "    mforce_literals = operands;",
                       f"    m68ki_cpu.ir = 0x{opcode:04x}u;",
                       "    REG_PC += 2;", "    {", body, "    }",
                       f"complete: USE_CYCLES({cycles});", "}", ""]
        (out / f"kernel_{batch:02}.c").write_text("\n".join(chunks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("fbneo", "generated", "rom", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--margin", type=int, default=48)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    original = read_program(args.rom)
    image = widen_screen_bounds(original, args.margin)
    ops = sorted({w for w, in struct.iter_unpack(">H", image)})
    bodies, table = decode_table((args.generated / "m68kops.c").read_text())
    cpu = args.fbneo / "src/cpu/m68k"
    generate_header(cpu, args.out)
    generate_core(cpu, table, args.out)
    write_kernels(ops, bodies, table, args.out)
    write_sites(image, ops, args.out)
    stats = {"cpu_sites": len(image) // 2,
             "reset_sp": int.from_bytes(image[0:4], "big"),
             "reset_pc": int.from_bytes(image[4:8], "big"),
             "decoded_operations": len(ops),
             "margin": args.margin,
             "program_sha256": hashlib.sha256(original).hexdigest(),
             "translated_sha256": hashlib.sha256(image).hexdigest()}
    (args.out / "translation.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
