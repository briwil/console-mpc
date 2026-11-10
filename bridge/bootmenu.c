/*
 * bootmenu.c - the startup menu: "PAD 1 = Console, PAD 2 = stock MPC", a few seconds, then the stock app.
 *
 *   bootmenu [seconds]      exit code 10 = Console, 11 = stock MPC app (also on timeout or any problem)
 *
 * The stock app must already be stopped (boot.sh does that). Draws on the 320x240 screen, lights pads 1 and 2,
 * reads the control surface. Built like the other tools (bridge/build.sh). Host test: -DHOST_TEST.
 */
#include <stdint.h>
#include <stddef.h>
#ifdef HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#else
extern int open(const char *, int, ...);
extern int close(int);
extern long read(int, void *, unsigned long);
extern long write(int, const void *, unsigned long);
extern int ioctl(int, unsigned long, ...);
extern long lseek(int, long, int);
extern int usleep(unsigned);
extern int atoi(const char *);
extern void *memset(void *, int, unsigned long);
extern int snprintf(char *, unsigned long, const char *, ...);
__asm__(".text\n.globl _start\n.type _start,%function\n_start:\n"
        "  mov x29, #0\n  mov x30, #0\n  mov x5, x0\n  ldr x1, [sp]\n  add x2, sp, #8\n  mov x6, sp\n"
        "  adrp x0, main\n  add x0, x0, :lo12:main\n  mov x3, #0\n  mov x4, #0\n"
        "  bl __libc_start_main\n  brk #0\n");
#endif
#include "font5x7.h"

#define O_RDWR_ 2
#define O_WRONLY_ 1
#define O_NONBLOCK_ 04000
#define FBIOGET_VSCREENINFO 0x4600
#define FBIOGET_FSCREENINFO 0x4602

static uint32_t shadow[320 * 240], outbuf[320 * 240];
static uint32_t roff = 16, goff = 8, boff = 0, fbstride = 1280;
static int fbfd = -1, midifd = -1;

struct fb_bitfield { uint32_t offset, length, msb_right; };
struct fb_var { uint32_t xres, yres, xv, yv, xo, yo, bpp, gray; struct fb_bitfield red, green, blue, transp; uint32_t rest[20]; };
struct fb_fix { char id[16]; unsigned long smem_start; uint32_t smem_len, type, type_aux, visual;
                uint16_t xpan, ypan, ywrap; uint32_t line_length; unsigned long mmio; uint32_t mmio_len, accel;
                uint16_t caps, reserved[2]; };

#ifdef HOST_TEST
static int tick_now;
static void host_ppm(const char *name)
{
    FILE *f = fopen(name, "wb");
    fprintf(f, "P6 320 240 255\n");
    for (int i = 0; i < 320 * 240; i++) { fputc((shadow[i] >> 16) & 255, f); fputc((shadow[i] >> 8) & 255, f); fputc(shadow[i] & 255, f); }
    fclose(f);
}
#endif

static void say(const char *s)
{
#ifdef HOST_TEST
    fputs(s, stdout);
#else
    unsigned long n = 0;
    while (s[n]) n++;
    write(1, s, n);
#endif
}

static void say_hex(const char *tag, const uint8_t *b, int n)
{
    char line[160];
    static const char hx[] = "0123456789ABCDEF";
    int k = 0;
    while (tag[k] && k < 20) { line[k] = tag[k]; k++; }
    for (int i = 0; i < n && k < 150; i++) { line[k++] = ' '; line[k++] = hx[b[i] >> 4]; line[k++] = hx[b[i] & 15]; }
    line[k++] = '\n'; line[k] = 0;
    say(line);
}

static void fb_open(void)
{
#ifndef HOST_TEST
    fbfd = open("/dev/fb0", O_RDWR_);
    if (fbfd < 0) return;
    struct fb_var v; struct fb_fix f;
    if (ioctl(fbfd, FBIOGET_VSCREENINFO, &v) == 0) {
        if (v.xres != 320 || v.yres != 240 || v.bpp != 32) { close(fbfd); fbfd = -1; return; }
        roff = v.red.offset; goff = v.green.offset; boff = v.blue.offset;
    }
    if (ioctl(fbfd, FBIOGET_FSCREENINFO, &f) == 0 && f.line_length) fbstride = f.line_length;
    int b = open("/sys/class/graphics/fb0/blank", O_WRONLY_);
    if (b >= 0) { write(b, "1", 1); write(b, "0", 1); close(b); }
#endif
}

static void flush(void)
{
#ifndef HOST_TEST
    if (fbfd < 0) return;
    for (int i = 0; i < 320 * 240; i++) {
        uint32_t c = shadow[i];
        outbuf[i] = (((c >> 16) & 255) << roff) | (((c >> 8) & 255) << goff) | ((c & 255) << boff);
    }
    if (fbstride == 1280) { lseek(fbfd, 0, 0); write(fbfd, outbuf, 320 * 240 * 4); }
    else for (int y = 0; y < 240; y++) { lseek(fbfd, (long)(y * fbstride), 0); write(fbfd, &outbuf[y * 320], 320 * 4); }
#endif
}

static void rect(int x, int y, int w, int h, uint32_t c)
{
    for (int j = y; j < y + h; j++)
        for (int i = x; i < x + w; i++)
            if (i >= 0 && i < 320 && j >= 0 && j < 240) shadow[j * 320 + i] = c;
}

static void text(int x, int y, const char *s, int sc, uint32_t col)
{
    for (; *s; s++, x += 6 * sc) {
        const unsigned char *g = FONT[(unsigned char)*s & 127];
        for (int c = 0; c < 5; c++)
            for (int r = 0; r < 7; r++)
                if (g[c] & (1 << r)) rect(x + c * sc, y + r * sc, sc, sc, col);
    }
}

#ifdef HOST_TEST
static uint8_t host_in[16]; static int host_in_n;
#endif

static void midi_write(const uint8_t *b, int n)
{
#ifndef HOST_TEST
    if (midifd >= 0) write(midifd, b, (unsigned long)n);
#else
    (void)b; (void)n;
#endif
}

static void pad_led(int pad, int r, int g, int b)
{
    uint8_t m[12] = { 0xF0, 0x47, 0x7F, 0x5C, 0x65, 0x00, 0x04, (uint8_t)pad, (uint8_t)r, (uint8_t)g, (uint8_t)b, 0xF7 };
    midi_write(m, 12);
}

static void midi_close(void);
static void midi_open(void)
{
#ifndef HOST_TEST
    for (int tries = 0; tries < 40 && midifd < 0; tries++) {     /* the stock app may still be letting go of it */
        midifd = open("/dev/snd/midiC0D0", O_RDWR_ | O_NONBLOCK_);
        if (midifd < 0) usleep(100000);
    }
    if (midifd < 0) { say("midi: could not open /dev/snd/midiC0D0\n"); return; }
    {                                   /* plain MIDI bytes, not the stock app's timestamped records */
        uint64_t p[6];
        memset(p, 0, sizeof p);
        ((int *)p)[0] = 1; p[1] = 4096; p[2] = 1;
        int r = ioctl(midifd, 0xC0305710UL, p);
        say(r == 0 ? "midi: opened, framing off\n" : "midi: opened, framing ioctl FAILED\n");
    }
#endif
}

static void midi_close(void)
{
#ifndef HOST_TEST
    if (midifd >= 0) { close(midifd); midifd = -1; }
#endif
}

static int midi_read(uint8_t *b, int max)
{
#ifdef HOST_TEST
    int n = host_in_n < max ? host_in_n : max;
    for (int i = 0; i < n; i++) b[i] = host_in[i];
    host_in_n -= n;
    return n;
#else
    if (midifd < 0) return 0;
    long r = read(midifd, b, (unsigned long)max);
    if (r > 0) {
        static int logged;
        if (logged < 25) { logged++; say_hex("midi in:", b, r > 24 ? 24 : (int)r); }
    }
    return r > 0 ? (int)r : 0;
#endif
}

static void draw(int secs_left)
{
    rect(0, 0, 320, 240, 0x00101418);
    text(24, 20, "STARTUP", 4, 0x00E8B04B);
    rect(24, 62, 272, 3, 0x00E8B04B);
    text(24, 90, "PAD 1  CONSOLE", 3, 0x00FFFFFF);
    text(24, 130, "PAD 2  MPC", 3, 0x00FFFFFF);
    char m[40];
#ifdef HOST_TEST
    snprintf(m, sizeof m, "MPC STARTS IN %d", secs_left);
#else
    snprintf(m, sizeof m, "MPC STARTS IN %d", secs_left);
#endif
    text(24, 190, m, 2, 0x008899AA);
}

int main(int argc, char **argv)
{
    int secs = argc > 1 ? atoi(argv[1]) : 6;
    if (secs < 2) secs = 2;
    if (secs > 30) secs = 30;
    fb_open();
    midi_open();
    pad_led(0, 0, 110, 20);
    pad_led(1, 70, 70, 70);
    for (int p = 2; p < 16; p++) pad_led(p, 0, 0, 0);
    int choice = 11, last = -1;
    uint8_t st = 0;
    int need = 0, n = 0, heard = 0;
    uint8_t d[2];
    for (int t = 0; t < secs * 50 && choice == 11; t++) {
#ifdef HOST_TEST
        tick_now = t;
        if (t == 5) host_ppm("boot_menu.ppm");
        if (t == 20 && getenv("PICK") && getenv("PICK")[0] == '1') { host_in[0] = 0x99; host_in[1] = 37; host_in[2] = 90; host_in_n = 3; }
#endif
        int left = secs - t / 50;
        if (left != last) { last = left; draw(left); flush(); }
        uint8_t buf[64];
        int k = midi_read(buf, sizeof buf), picked = 0;
        if (k > 0) heard = 1;
        if (!heard && t > 0 && t % 100 == 0) {      /* silent so far: let go of the port, reopen it, light the pads again */
            midi_close(); midi_open();
            pad_led(0, 0, 110, 20); pad_led(1, 70, 70, 70);
            for (int p = 2; p < 16; p++) pad_led(p, 0, 0, 0);
        }
        for (int i = 0; i < k; i++) {
            uint8_t b = buf[i];
            if (b >= 0xF8) continue;
            if (b & 0x80) { st = b; n = 0; need = ((b & 0xF0) == 0xC0 || (b & 0xF0) == 0xD0) ? 1 : (b >= 0xF0 ? 99 : 2); continue; }
            if (!st || need == 99) continue;
            d[n++] = b;
            if (n < need) continue;
            n = 0;
            if (st == 0x99 && d[1] > 0) { if (d[0] == 37) picked = 10; else if (d[0] == 36) picked = 11; }
        }
        if (picked == 10) {
            choice = 10;
            rect(0, 0, 320, 240, 0x00101418);
            text(24, 100, "STARTING CONSOLE", 3, 0x00E8B04B);
            flush();
        }
        if (picked == 11) break;
#ifdef HOST_TEST
        usleep(1000);
#else
        usleep(20000);
#endif
    }
    for (int p = 0; p < 16; p++) pad_led(p, 0, 0, 0);
    return choice;
}
