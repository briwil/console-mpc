/* Console's screen text, drawn in C: the pages draw dozens of words a frame, and doing each in numpy was the slowest part of a frame
 * on the MPC Sample. A word is an 8-bit mask (0..255) made once in Python (and kept); this puts it on the 320 x 240 RGB canvas in a
 * colour, clipped to the screen. Python falls back to numpy when this library is not there (native.py). */
#include <stdint.h>

void dt_blend(uint8_t *px, int W, int H, int x, int y, const uint8_t *m, int mw, int mh, int r, int g, int b)
{
    for (int j = 0; j < mh; j++) {
        int yy = y + j;
        if (yy < 0 || yy >= H) continue;
        const uint8_t *row = m + (long)j * mw;
        uint8_t *dst = px + ((long)yy * W) * 3;
        for (int i = 0; i < mw; i++) {
            int xx = x + i;
            uint8_t a = row[i];
            if (!a || xx < 0 || xx >= W) continue;
            uint8_t *d = dst + (long)xx * 3;
            if (a == 255) { d[0] = (uint8_t)r; d[1] = (uint8_t)g; d[2] = (uint8_t)b; }
            else {
                d[0] = (uint8_t)((d[0] * (255 - a) + r * a + 127) / 255);
                d[1] = (uint8_t)((d[1] * (255 - a) + g * a + 127) / 255);
                d[2] = (uint8_t)((d[2] * (255 - a) + b * a + 127) / 255);
            }
        }
    }
}
