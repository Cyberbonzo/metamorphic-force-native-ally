#ifndef MFORCE_BOARD_H
#define MFORCE_BOARD_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The arcade raster is 288x224 on a 4:3 monitor. 48 extra columns on either
 * side give a 384x224 raster that fills 16:9 with the original pixel shape. */
#ifndef MFORCE_MARGIN_VALUE
#define MFORCE_MARGIN_VALUE 48
#endif
enum {
    MFORCE_ARCADE_WIDTH = 288,
    MFORCE_MARGIN = MFORCE_MARGIN_VALUE,
    MFORCE_WIDTH = MFORCE_ARCADE_WIDTH + 2 * MFORCE_MARGIN,
    MFORCE_HEIGHT = 224,
    MFORCE_AUDIO_RATE = 48000,
    MFORCE_MAX_AUDIO_FRAMES = 2048
};

enum {
    MFORCE_UP = 1, MFORCE_DOWN = 2, MFORCE_LEFT = 4, MFORCE_RIGHT = 8,
    MFORCE_ATTACK = 16, MFORCE_JUMP = 32, MFORCE_SPECIAL = 64,
    MFORCE_START = 128, MFORCE_COIN = 256
};

/* The game-specific board consumes extracted, CRC-verified chips. */
int mforce_init(const char *directory);
/* Optional, before init: keep the arcade EEPROM (settings, high scores) here. */
int mforce_set_save_dir(const char *directory);
double mforce_fps(void);
/* XRGB8888, top to bottom, and interleaved 48 kHz signed stereo.
 * Return stereo frame count, or a negative value on a board error. */
int mforce_frame(uint32_t *pixels, int16_t *stereo, unsigned p1, unsigned p2);
void mforce_shutdown(void);

/* Zero size indicates that this build has no verified save-state implementation.
 * Save and load return zero on success. A rejected load leaves the board intact. */
size_t mforce_state_size(void);
int mforce_save_state(void *out, size_t size);
int mforce_load_state(const void *data, size_t size);

#ifdef __cplusplus
}
#endif
#endif
