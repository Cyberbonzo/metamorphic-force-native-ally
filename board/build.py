#!/usr/bin/env python3
"""Build the single-title Metamorphic Force board from the pinned FBNeo device sources."""
import argparse
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("MFORCE_WORK", HERE.parent / ".work")).resolve()
FB = ROOT / "vendor/FBNeo"
SRC = FB / "src"
BUILD = ROOT / "build"
GEN = BUILD / "generated"
OBJ = BUILD / "board-obj"
MARGIN = int(os.environ.get("MFORCE_MARGIN", "48"))
SOURCE_FILES = """
burn/burn.cpp burn/burn_memory.cpp burn/tiles_generic.cpp burn/tilemap_generic.cpp
burn/burn_bitmap.cpp burn/debug_track.cpp burn/burn_sound.cpp burn/burn_sound_c.cpp burn/load.cpp burn/timer.cpp
burn/snd/burn_ym2151.cpp burn/snd/ym2151.c burn/snd/k054539.cpp
burn/devices/eeprom.cpp burn/devices/dtimer.cpp burn/devices/k053936.cpp
burn/drv/konami/konamiic.cpp burn/drv/konami/k055555.cpp burn/drv/konami/k054338.cpp
burn/drv/konami/k056832.cpp burn/drv/konami/k053247.cpp burn/drv/konami/k053250.cpp
burn/drv/konami/konamigx.cpp burn/drv/konami/k053251.cpp burn/drv/konami/k054000.cpp
burn/drv/konami/k051733.cpp burn/drv/konami/k051960.cpp burn/drv/konami/k052109.cpp burn/drv/konami/k053245.cpp
cpu/m68000_intf.cpp cpu/z80_intf.cpp cpu/z80/z80.cpp cpu/z80/z80daisy.cpp cpu/z80/z80ctc.cpp
""".split()
DEFINES = ["-DLSB_FIRST", "-DEMU_M68K", "-DBUILD_HEADLESS", "-DBUILD_X64_EXE", "-DNO_VIZ",
           "-DHAVE_UNISTD_H", f"-DMFORCE_MARGIN_VALUE={MARGIN}"]


def update(path, data):
    if not path.exists() or path.read_text() != data:
        path.write_text(data)


def replace_once(code, before, after):
    assert code.count(before) == 1, before
    return code.replace(before, after)


def prepare():
    OBJ.mkdir(exist_ok=True, parents=True)
    GEN.mkdir(exist_ok=True, parents=True)
    update(GEN / "driverlist.h", """extern struct BurnDriver BurnDrvMetamrpha;
static struct BurnDriver *const pDriver[] = { &BurnDrvMetamrpha };
static const struct {const char *game_name; char *sourcefile;} sourcefile_table[] = {
    {"metamrpha", (char*)"d_mystwarr.cpp"}, {"", (char*)""}};
""")
    code = (SRC / "burn/drv/konami/d_mystwarr.cpp").read_text()
    # 60 Hz logic: the board runs one video frame per display refresh of the
    # Ally. The arcade refresh was 59.185606 Hz; game speed rises by 1.38%.
    code = code.replace("59.185606", "60.0")
    code = code.replace('#include "dtimer.h"', '#include "dtimer.h"\n#include "mforce_board.h"', 1)
    # Wider raster for this title only; scroll origins move left by the margin.
    block = re.search(r"struct BurnDriver BurnDrvMetamrpha = \{.*?\n\};", code, re.S).group(0)
    code = code.replace(block, replace_once(block, "288, 224, 4, 3", "MFORCE_WIDTH, 224, 16, 9"))
    init = re.search(r"static INT32 MetamrphInit\(\)\n\{.*?\n\}\n", code, re.S).group(0)
    wide = init
    # K056832 clamps its global origin at zero; the rest of the margin moves
    # each layer's scroll origin instead.
    code = code.replace('#include "mforce_board.h"', '''#include "mforce_board.h"
#define MF_TILE_GX ((24 - MFORCE_MARGIN) < 0 ? 0 : (24 - MFORCE_MARGIN))
#define MF_TILE_LX (MFORCE_MARGIN - (24 - MF_TILE_GX))''', 1)
    for before, after in [
        ("K056832SetGlobalOffsets(24, 15);", "K056832SetGlobalOffsets(MF_TILE_GX, 15);"),
        ("K056832SetLayerOffsets(0, -2+4, 2);", "K056832SetLayerOffsets(0, -2+4 + MF_TILE_LX, 2);"),
        ("K056832SetLayerOffsets(1,  0+4, 2);", "K056832SetLayerOffsets(1,  0+4 + MF_TILE_LX, 2);"),
        ("K056832SetLayerOffsets(2,  2+4, 2);", "K056832SetLayerOffsets(2,  2+4 + MF_TILE_LX, 2);"),
        ("K056832SetLayerOffsets(3,  3+4, 2);", "K056832SetLayerOffsets(3,  3+4 + MF_TILE_LX, 2);"),
        ("K053247SetSpriteOffset(-51-24, -24-15+0);", "K053247SetSpriteOffset(-51-24 + MFORCE_MARGIN, -24-15+0);"),
        ("K053250SetOffsets(0, -60+29, -16);", "K053250SetOffsets(0, -60+29 + MFORCE_MARGIN, -16);"),
    ]:
        wide = replace_once(wide, before, after)
    code = code.replace(init, wide)
    # The adapter reads game state from main RAM (0x200000-0x20ffff).
    code += "\nUINT8 *mforce_main_ram() { return Drv68KRAM; }\n"
    update(GEN / "mforce_devices.cpp", code)


def compile_object(source):
    cpp = source.suffix == ".cpp"
    flags = [os.environ.get("CXX", "g++") if cpp else os.environ.get("CC", "gcc"),
             "-std=gnu++17" if cpp else "-std=gnu17", "-O2", "-fPIC",
             "-fvisibility=hidden", "-ffunction-sections", "-fdata-sections",
             "-fno-strict-aliasing", "-Wno-write-strings", "-Wno-narrowing", *DEFINES]
    includes = [SRC/"burn", SRC/"burn/devices", SRC/"burn/snd", SRC/"cpu", SRC/"cpu/m68k", SRC/"cpu/z80",
                SRC/"burner/headless", SRC/"burner", SRC/"intf", SRC/"burn/drv/konami", GEN,
                HERE.parent/"frontend"]
    out = OBJ / (source.name + ".o")
    if source.parent.name == "z80":  # z80.h expects z80_intf.h's calling-convention macro
        flags += ["-include", "burnint.h", "-include", "z80_intf.h"]
    subprocess.run(flags + [f"-I{x}" for x in includes] + ["-c", str(source), "-o", str(out)], check=True)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aot-object", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    prepare()
    sources = [SRC / s for s in SOURCE_FILES] + [GEN/"mforce_devices.cpp", HERE/"mforce_board.cpp", HERE/"standalone.cpp"]
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 6) as pool:
        objects = list(pool.map(compile_object, sources))
    subprocess.run(["g++", "-shared", "-Wl,--gc-sections,-z,defs", "-o", str(BUILD/"libmforce_board.so"),
                    *map(str, objects + args.aot_object), "-lz", "-lm", "-pthread"], check=True)


if __name__ == "__main__":
    main()
