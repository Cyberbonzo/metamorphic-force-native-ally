// Single-title Konami GX224 (Mystic Warriors family) peripheral and input adapter.
#include "burnint.h"
#include "timer.h"
#pragma GCC visibility push(default)
#include "mforce_board.h"
#pragma GCC visibility pop
#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <unordered_map>
#include <vector>
#include <zlib.h>

extern BurnDriver BurnDrvMetamrpha;
UINT8 *mforce_main_ram();
// Development aid: copy of 68000 main RAM in bus order (big-endian words).
extern "C" __attribute__((visibility("default"))) int mforce_debug_ram(uint8_t *out, size_t size) {
    UINT8 *ram = mforce_main_ram();
    if (!ram || size < 0x10000) return -1;
    for (size_t i = 0; i < 0x10000; ++i) out[i] = ram[i ^ 1];
    return 0;
}
static std::unordered_map<uint32_t, std::vector<unsigned char>> chips;
static bool active;

// Position of the driver inputs in MetamrphInputList.
enum { PLAYER_INPUTS = 9, DIP_A = 40 };

static INT32 load_chip(UINT8 *dst, INT32 *written, INT32 index) {
    BurnRomInfo rom{};
    if (BurnDrvMetamrpha.GetRomInfo(&rom, index)) return 1;
    auto chip = chips.find(rom.nCrc);
    if (chip == chips.end() || chip->second.size() != rom.nLen) {
        fprintf(stderr, "Missing chip %08x (index %d)\n", rom.nCrc, index);
        return 1;
    }
    memcpy(dst, chip->second.data(), rom.nLen);
    if (written) *written = rom.nLen;
    return 0;
}

static UINT32 xrgb(INT32 r, INT32 g, INT32 b, INT32) {
    return (r << 16) | (g << 8) | b;
}

int mforce_init(const char *directory) {
    if (active || !directory) return -1;
    chips.clear();
    try {
        for (const auto &f : std::filesystem::directory_iterator(directory)) {
            if (!f.is_regular_file() || f.file_size() > 4*1024*1024 || !f.file_size()) continue;
            std::ifstream stream(f.path(), std::ios::binary);
            std::vector<unsigned char> bytes(f.file_size());
            if (!stream.read(reinterpret_cast<char *>(bytes.data()), bytes.size())) return -1;
            const auto crc = crc32(0, bytes.data(), bytes.size());
            chips.emplace(crc, std::move(bytes));
        }
    } catch (const std::exception &e) {
        fprintf(stderr, "Reading chip directory: %s\n", e.what());
        return -1;
    }
    BurnLibInit();
    nBurnDrvActive = 0;
    nBurnBpp = 4;
    nBurnPitch = MFORCE_WIDTH * nBurnBpp;
    nBurnSoundRate = MFORCE_AUDIO_RATE;
    BurnHighCol = xrgb;
    BurnExtLoadRom = load_chip;
    BurnInitMemoryManager();
    BurnTimerPreInit();
    {
        // Stereo, common coin slot, two players, no continuous energy increment.
        BurnInputInfo input{};
        BurnDrvMetamrpha.GetInputInfo(&input, DIP_A);
        *input.pVal = 0xe0;
    }
    const auto result = BurnDrvMetamrpha.Init();
    chips.clear();
    if (result != 0) {
        BurnExitMemoryManager();
        BurnLibExit();
        return -1;
    }
    active = true;
    return 0;
}

// Boot tests, the story, title, player select, Hall of Fame and logo screens
// only draw the 288 arcade columns; whatever the extra columns hold there is
// stale tile data. Byte 0x2027c1 of main RAM is 32 while a stage is running
// (attract demos, play, continue, stage maps) and 0 on those screens. The
// stage-clear emblem runs inside a stage; byte 0x202a16 is 3 only there.
// Left of camera X 0 (word 0x202824) there is no map; in the columns that fall
// there, the colour covering most of them (the backdrop) becomes black, so
// characters walking in stay visible. RAM is stored byte-swapped by FBNeo on
// little-endian hosts; aligned words read natively.
static void blacken_dominant(uint32_t *pixels, int x0, int x1) {
    std::unordered_map<uint32_t, int> count;
    for (int y = 0; y < MFORCE_HEIGHT; y += 2)
        for (int x = x0; x < x1; x += 2) ++count[pixels[y * MFORCE_WIDTH + x]];
    uint32_t dominant = 0;
    int best = 0;
    for (const auto &[colour, n] : count) if (n > best) { best = n; dominant = colour; }
    for (int y = 0; y < MFORCE_HEIGHT; ++y)
        for (int x = x0; x < x1; ++x)
            if (pixels[y * MFORCE_WIDTH + x] == dominant) pixels[y * MFORCE_WIDTH + x] = 0;
}

static void hide_unused_margins(uint32_t *pixels) {
    if (!MFORCE_MARGIN) return;
    const UINT8 *ram = mforce_main_ram();
    int left = MFORCE_MARGIN, right = MFORCE_MARGIN;
    if (ram[0x27c1 ^ 1] == 32 && ram[0x2a16 ^ 1] != 3) {
        left = right = 0;
        const int camera = *reinterpret_cast<const INT16 *>(ram + 0x2824);
        const int outside = std::clamp(MFORCE_MARGIN - camera, 0, static_cast<int>(MFORCE_MARGIN));
        if (outside) blacken_dominant(pixels, 0, outside);
    }
    for (int y = 0; y < MFORCE_HEIGHT; ++y) {
        uint32_t *row = pixels + y * MFORCE_WIDTH;
        std::fill(row, row + left, 0u);
        std::fill(row + MFORCE_WIDTH - right, row + MFORCE_WIDTH, 0u);
    }
    // Some sections (the cliff climb, fixed rooms) are only 288 columns wide:
    // their extra columns show nothing but the backdrop colour. When nearly
    // the whole side is one colour, that colour becomes black; sprites that
    // cross into it stay visible.
    for (const int x0 : {0, static_cast<int>(MFORCE_WIDTH - MFORCE_MARGIN)}) {
        const uint32_t backdrop = pixels[(MFORCE_HEIGHT / 2) * MFORCE_WIDTH + x0 + MFORCE_MARGIN / 2];
        int same = 0;
        for (int y = 0; y < MFORCE_HEIGHT; ++y)
            for (int x = x0; x < x0 + MFORCE_MARGIN; ++x)
                same += pixels[y * MFORCE_WIDTH + x] == backdrop;
        if (!backdrop || same * 100 < MFORCE_HEIGHT * MFORCE_MARGIN * 97) continue;
        for (int y = 0; y < MFORCE_HEIGHT; ++y)
            for (int x = x0; x < x0 + MFORCE_MARGIN; ++x)
                if (pixels[y * MFORCE_WIDTH + x] == backdrop) pixels[y * MFORCE_WIDTH + x] = 0;
    }
}

int mforce_set_save_dir(const char *directory) {
    if (active || !directory) return -1;
    const size_t n = strlen(directory);
    if (!n || n + 2 + sizeof("metamrpha.nv") > MAX_PATH) return -1;
    snprintf(szAppEEPROMPath, MAX_PATH, "%s%s", directory, directory[n - 1] == '/' ? "" : "/");
    return 0;
}

double mforce_fps() { return nBurnFPS / 100.0; }

int mforce_frame(uint32_t *pixels, int16_t *audio, unsigned p1, unsigned p2) {
    if (!active || !pixels || !audio) return -1;
    const unsigned players[2] = {p1, p2};
    // Input list order: coin, start, up, down, left, right, button 1-3.
    static const std::array<unsigned, PLAYER_INPUTS> masks = {
        MFORCE_COIN, MFORCE_START, MFORCE_UP, MFORCE_DOWN, MFORCE_LEFT, MFORCE_RIGHT,
        MFORCE_ATTACK, MFORCE_JUMP, MFORCE_SPECIAL};
    for (int p = 0; p < 2; ++p) for (int i = 0; i < PLAYER_INPUTS; ++i) {
        BurnInputInfo input{};
        BurnDrvMetamrpha.GetInputInfo(&input, p * PLAYER_INPUTS + i);
        *input.pVal = (players[p] & masks[i]) != 0;
    }
    pBurnDraw = reinterpret_cast<UINT8 *>(pixels);
    pBurnSoundOut = audio;
    memset(audio, 0, sizeof(*audio) * 2 * nBurnSoundLen);
    ++nCurrentFrame;
    if (BurnDrvMetamrpha.Frame() != 0) return -1;
    hide_unused_margins(pixels);
    return nBurnSoundLen;
}

void mforce_shutdown() {
    if (!active) return;
    BurnDrvMetamrpha.Exit();
    BurnExitMemoryManager();
    BurnLibExit();
    active = false;
}

#include "../frontend/board_progress.inc"
