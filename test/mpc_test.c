/*
 * mpc_test.c - hardware test for the Akai MPC Sample (firmware 1.3.0)
 *
 * Stops the stock MPC app, then:
 *   - draws on the 320x240 screen (/dev/fb0),
 *   - plays a tone from each pad through the audio output (ALSA card 2, S32_LE, 44.1 kHz, 128 frames),
 *   - lights the pads (SysEx) and echoes button lights,
 *   - shows every pad / button / knob / encoder message it receives.
 * Quit with SHIFT + STOP (on the MPC) or Ctrl+C. The stock app is started again on the way out.
 *
 * Control surface protocol (found with the logger, Nov 2026), all on /dev/snd/midiC0D0:
 *   pads      channel 10: Note On / Note Off / poly pressure; notes 37 36 42 82 / 40 38 46 44 / 48 47 45 43 / 49 55 51 53
 *   buttons   channel 1:  Note On 7F (press) / Note Off (release)
 *   knobs     channel 1:  CC 0x10 K1, 0x11 K2, 0x12 K3, 0x13 MAIN VOLUME, 0x14 FADER (absolute 0-127)
 *   encoder   channel 1:  CC 0x64, relative (01 = one click up, 7F = one click down)
 *   pad light SysEx  F0 47 7F 5C 65 00 04 <pad 0-15> <R> <G> <B> F7   (7-bit colours)
 *   button light (guess, tested here)  CC <button note> 7F / 00
 *
 * Built without any ARM headers: see build.sh. Host test: gcc -DHOST_TEST (simulated hardware).
 */
#include <stdint.h>
#include <stddef.h>

#ifdef HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#else
extern int open(const char *, int, ...);
extern int close(int);
extern long read(int, void *, unsigned long);
extern long write(int, const void *, unsigned long);
extern int ioctl(int, unsigned long, ...);
extern long lseek(int, long, int);
extern int usleep(unsigned);
extern int system(const char *);
typedef void (*sighandler_t)(int);
extern sighandler_t signal(int, sighandler_t);
extern int snd_pcm_open(void **, const char *, int, int);
extern int snd_pcm_set_params(void *, int, int, unsigned, unsigned, int, unsigned);
extern long snd_pcm_writei(void *, const void *, unsigned long);
extern int snd_pcm_recover(void *, int, int);
extern int snd_pcm_close(void *);
#endif

#include "font5x7.h"

#ifndef HOST_TEST
/* program entry: what glibc's crt1.o does on aarch64 (we have no crt files here) */
__asm__(".text\n.globl _start\n.type _start,%function\n_start:\n"
        "  mov x29, #0\n  mov x30, #0\n  mov x5, x0\n  ldr x1, [sp]\n  add x2, sp, #8\n  mov x6, sp\n"
        "  adrp x0, main\n  add x0, x0, :lo12:main\n  mov x3, #0\n  mov x4, #0\n"
        "  bl __libc_start_main\n  brk #0\n");
#endif

/* ---------------------------------------------------------------- small helpers */

static void say(const char *s)
{
#ifdef HOST_TEST
    fputs(s, stdout);
#else
    unsigned long n = 0;
    while (s[n])
        n++;
    write(1, s, n);
#endif
}

static int slen(const char *s)
{
    int n = 0;
    while (s[n])
        n++;
    return n;
}

static char *scat(char *d, const char *s)
{
    while (*s)
        *d++ = *s++;
    *d = 0;
    return d;
}

static char *sint(char *d, int v)
{
    char t[12];
    int n = 0;
    if (v < 0) {
        *d++ = '-';
        v = -v;
    }
    if (v == 0)
        t[n++] = '0';
    while (v) {
        t[n++] = (char)('0' + v % 10);
        v /= 10;
    }
    while (n)
        *d++ = t[--n];
    *d = 0;
    return d;
}

static char *shex(char *d, int v)
{
    static const char h[] = "0123456789ABCDEF";
    *d++ = '0';
    *d++ = 'X';
    *d++ = h[(v >> 4) & 15];
    *d++ = h[v & 15];
    *d = 0;
    return d;
}

/* ---------------------------------------------------------------- the controls */

static const uint8_t PADNOTE[16] = { 37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53 };

struct btn { uint8_t note; const char *name; };
static const struct btn BTNS[] = {
    { 0x31, "SHIFT" }, { 0x52, "PLAY" }, { 0x51, "STOP" }, { 0x50, "SEQ REC" },
    { 0x09, "ERASE" }, { 0x06, "SAMPLE" }, { 0x07, "SEQ" }, { 0x2B, "MUTE" },
    { 0x23, "PAD BANK" }, { 0x01, "PAD FX" }, { 0x00, "KNOB FX" }, { 0x35, "TAP TEMPO" },
    { 0x49, "SAMPLE REC" }, { 0x0C, "B1" }, { 0x0D, "B2" }, { 0x0E, "B3" },
    { 0x28, "16 LEVELS" }, { 0x4B, "CHOP" }, { 0x0B, "NOTE REPEAT" },
    { 0x6F, "ENC PUSH" }, { 0x36, "PLUS" }, { 0x37, "MINUS" },
};
#define NBTNS ((int)(sizeof BTNS / sizeof BTNS[0]))
#define NOTE_SHIFT 0x31
#define NOTE_STOP 0x51

static const char *KNOBNAME[5] = { "K1", "K2", "K3", "VOL", "FAD" };

/* ---------------------------------------------------------------- state */

static volatile int quit;
static int shift_down;
static int pad_down[16], pad_vel[16];
static int knob[5] = { -1, -1, -1, -1, -1 };
static int enc_total, enc_seen;
static char logl[5][28];
static int dirty = 1;

static void add_log(const char *s)
{
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 28; j++)
            logl[i][j] = logl[i + 1][j];
    int n = slen(s);
    if (n > 26)
        n = 26;
    for (int j = 0; j < n; j++)
        logl[4][j] = s[j];
    logl[4][n] = 0;
    say(s);
    say("\n");
    dirty = 1;
}

/* ---------------------------------------------------------------- hardware layer */

#ifndef HOST_TEST
#define O_RDWR_ 2
#define O_WRONLY_ 1
#define O_NONBLOCK_ 04000
#define FBIOGET_VSCREENINFO 0x4600
#define FBIOGET_FSCREENINFO 0x4602

struct fb_bitfield { uint32_t offset, length, msb_right; };
struct fb_var {
    uint32_t xres, yres, xres_virtual, yres_virtual, xoffset, yoffset, bits_per_pixel, grayscale;
    struct fb_bitfield red, green, blue, transp;
    uint32_t nonstd, activate, height, width, accel_flags, pixclock, left_margin, right_margin,
        upper_margin, lower_margin, hsync_len, vsync_len, sync, vmode, rotate, colorspace, reserved[4];
};
struct fb_fix {
    char id[16];
    unsigned long smem_start;
    uint32_t smem_len, type, type_aux, visual;
    uint16_t xpanstep, ypanstep, ywrapstep;
    uint32_t line_length;
    unsigned long mmio_start;
    uint32_t mmio_len, accel;
    uint16_t capabilities, reserved[2];
};
static int fbfd = -1;
static void *pcm;
static int midifd = -1;
#endif

static uint32_t fbw = 320, fbh = 240, fbstride = 1280, fbbpp = 32;
static uint32_t roff = 16, goff = 8, boff = 0;
static uint32_t shadow[320 * 240];   /* 0x00RRGGBB */
static uint32_t outbuf[320 * 240];
static int audio_ok, midi_ok, fb_ok;

#ifdef HOST_TEST
static int32_t host_audio[44100 * 6 * 2];
static long host_audio_n;
static FILE *host_midi_out;
static unsigned char host_in[256];
static int host_in_n;
static long host_tick;

static void host_ppm(const char *name)
{
    FILE *f = fopen(name, "wb");
    fprintf(f, "P6\n%u %u\n255\n", fbw, fbh);
    for (uint32_t i = 0; i < fbw * fbh; i++) {
        uint32_t c = outbuf[i];
        unsigned char px[3] = { (unsigned char)((c >> roff) & 255), (unsigned char)((c >> goff) & 255),
                                (unsigned char)((c >> boff) & 255) };
        fwrite(px, 1, 3, f);
    }
    fclose(f);
}

static void host_feed(const unsigned char *b, int n)
{
    for (int i = 0; i < n; i++)
        host_in[host_in_n++] = b[i];
}

/* a scripted "player": what a person might do on the device */
static void host_script(long t)
{
    static const unsigned char pad1on[] = { 0x99, 37, 100, 0xA9, 37, 5 };
    static const unsigned char pad1off[] = { 0x89, 37, 0 };
    static const unsigned char pad13on[] = { 0x99, 49, 81 };
    static const unsigned char pad7on[] = { 0x99, 46, 127, 0x99, 40, 60 };
    static const unsigned char k1[] = { 0xB0, 0x10, 64 };
    static const unsigned char k3[] = { 0xB0, 0x12, 20 };
    static const unsigned char vol[] = { 0xB0, 0x13, 100, 0xB0, 0x14, 127 };
    static const unsigned char enc[] = { 0xB0, 0x64, 1, 0xB0, 0x64, 1, 0xB0, 0x64, 1, 0xB0, 0x64, 0x7F };
    static const unsigned char tapon[] = { 0x90, 0x35, 0x7F };
    static const unsigned char tapoff[] = { 0x80, 0x35, 0 };
    static const unsigned char unknown[] = { 0x90, 0x77, 0x7F, 0x80, 0x77, 0 };
    static const unsigned char sx[] = { 0xF0, 0x7E, 0, 6, 2, 0x47, 0xF7, 0xB0, 0x10, 70 };   /* a stray SysEx mid-stream */
    static const unsigned char shiftdn[] = { 0x90, NOTE_SHIFT, 0x7F };
    static const unsigned char stopdn[] = { 0x90, NOTE_STOP, 0x7F };
    switch (t) {
    case 10: host_feed(pad1on, sizeof pad1on); break;
    case 60: host_feed(pad1off, sizeof pad1off); break;
    case 70: host_feed(pad13on, sizeof pad13on); break;
    case 80: host_feed(pad7on, sizeof pad7on); break;
    case 90: host_feed(k1, sizeof k1); break;
    case 95: host_feed(k3, sizeof k3); break;
    case 100: host_feed(vol, sizeof vol); break;
    case 110: host_feed(enc, sizeof enc); break;
    case 120: host_feed(tapon, sizeof tapon); break;
    case 130: host_feed(tapoff, sizeof tapoff); break;
    case 140: host_feed(unknown, sizeof unknown); break;
    case 150: host_feed(sx, sizeof sx); break;
    case 200: host_feed(shiftdn, sizeof shiftdn); break;
    case 260: host_feed(stopdn, sizeof stopdn); break;
    }
}
#endif

static int fb_init(void)
{
#ifdef HOST_TEST
    return 1;
#else
    fbfd = open("/dev/fb0", O_RDWR_);
    if (fbfd < 0) {
        say("fb: cannot open /dev/fb0\n");
        return 0;
    }
    struct fb_var v;
    struct fb_fix f;
    if (ioctl(fbfd, FBIOGET_VSCREENINFO, &v) == 0) {
        fbw = v.xres;
        fbh = v.yres;
        fbbpp = v.bits_per_pixel;
        roff = v.red.offset;
        goff = v.green.offset;
        boff = v.blue.offset;
    }
    fbstride = fbw * 4;
    if (ioctl(fbfd, FBIOGET_FSCREENINFO, &f) == 0 && f.line_length)
        fbstride = f.line_length;
    char m[96];
    char *p = scat(m, "fb: ");
    p = sint(p, (int)fbw);
    p = scat(p, "x");
    p = sint(p, (int)fbh);
    p = scat(p, " bpp ");
    p = sint(p, (int)fbbpp);
    p = scat(p, " stride ");
    p = sint(p, (int)fbstride);
    p = scat(p, " rgb offsets ");
    p = sint(p, (int)roff);
    p = scat(p, ",");
    p = sint(p, (int)goff);
    p = scat(p, ",");
    p = sint(p, (int)boff);
    scat(p, "\n");
    say(m);
    if (fbw > 320 || fbh > 240 || fbbpp != 32) {
        say("fb: unexpected format (need 320x240 at 32 bits); screen disabled\n");
        return 0;
    }
    /* what SampQOL does before it draws its splash */
    int b = open("/sys/class/graphics/fb0/blank", O_WRONLY_);
    if (b >= 0) {
        write(b, "1", 1);
        write(b, "0", 1);
        close(b);
    }
    return 1;
#endif
}

static void fb_flush(void)
{
    if (!fb_ok)
        return;
    for (uint32_t i = 0; i < fbw * fbh; i++) {
        uint32_t c = shadow[i];
        outbuf[i] = (((c >> 16) & 255) << roff) | (((c >> 8) & 255) << goff) | ((c & 255) << boff);
    }
#ifdef HOST_TEST
    if (host_tick == 215 || host_tick == 100)
        host_ppm(host_tick == 100 ? "shot_a.ppm" : "shot_b.ppm");
#else
    if (fbstride == fbw * 4) {
        lseek(fbfd, 0, 0);
        write(fbfd, outbuf, fbw * fbh * 4);
    } else {
        for (uint32_t y = 0; y < fbh; y++) {
            lseek(fbfd, (long)(y * fbstride), 0);
            write(fbfd, &outbuf[y * fbw], fbw * 4);
        }
    }
#endif
}

static int audio_init(void)
{
#ifdef HOST_TEST
    return 1;
#else
    for (int tries = 0; tries < 25; tries++) {
        int r = snd_pcm_open(&pcm, "hw:2,0", 0, 0);
        if (r == 0) {
            /* S32_LE = 10, RW_INTERLEAVED = 3, 2 channels, 44100, no resampling, 12 ms */
            r = snd_pcm_set_params(pcm, 10, 3, 2, 44100, 0, 12000);
            if (r == 0)
                return 1;
            say("audio: snd_pcm_set_params failed\n");
            snd_pcm_close(pcm);
            return 0;
        }
        usleep(200000);
    }
    say("audio: cannot open hw:2,0\n");
    return 0;
#endif
}

static void audio_write(const int32_t *fr, int n)
{
#ifdef HOST_TEST
    if (host_audio_n + n * 2 <= (long)(sizeof host_audio / sizeof host_audio[0])) {
        for (int i = 0; i < n * 2; i++)
            host_audio[host_audio_n++] = fr[i];
    }
#else
    while (n > 0) {
        long r = snd_pcm_writei(pcm, fr, (unsigned long)n);
        if (r < 0) {
            if (snd_pcm_recover(pcm, (int)r, 1) < 0)
                return;
            continue;
        }
        fr += r * 2;
        n -= (int)r;
    }
#endif
}

static int midi_init(void)
{
#ifdef HOST_TEST
    host_midi_out = fopen("midi_out.txt", "w");
    return 1;
#else
    for (int tries = 0; tries < 25; tries++) {
        midifd = open("/dev/snd/midiC0D0", O_RDWR_ | O_NONBLOCK_);
        if (midifd >= 0)
            return 1;
        usleep(200000);
    }
    say("midi: cannot open /dev/snd/midiC0D0\n");
    return 0;
#endif
}

static int midi_read(uint8_t *b, int max)
{
#ifdef HOST_TEST
    int n = host_in_n < max ? host_in_n : max;
    for (int i = 0; i < n; i++)
        b[i] = host_in[i];
    for (int i = n; i < host_in_n; i++)
        host_in[i - n] = host_in[i];
    host_in_n -= n;
    return n;
#else
    long r = read(midifd, b, (unsigned long)max);
    return r > 0 ? (int)r : 0;
#endif
}

static void midi_send(const uint8_t *b, int n)
{
    if (!midi_ok)
        return;
#ifdef HOST_TEST
    for (int i = 0; i < n; i++)
        fprintf(host_midi_out, "%02X ", b[i]);
    fprintf(host_midi_out, "\n");
#else
    int off = 0, spins = 0;
    while (off < n && spins < 200) {
        long r = write(midifd, b + off, (unsigned long)(n - off));
        if (r > 0)
            off += (int)r;
        else {
            usleep(500);
            spins++;
        }
    }
#endif
}

/* ---------------------------------------------------------------- lights */

static void pad_led(int pad, int r, int g, int b)
{
    uint8_t m[12] = { 0xF0, 0x47, 0x7F, 0x5C, 0x65, 0x00, 0x04, (uint8_t)pad, (uint8_t)r, (uint8_t)g, (uint8_t)b, 0xF7 };
    midi_send(m, 12);
}

static void pad_idle(int pad)
{
    pad_led(pad, 0x00, 0x0C, 0x28);
}

static void btn_led(int note, int on)
{
    uint8_t m[3] = { 0xB0, (uint8_t)note, (uint8_t)(on ? 0x7F : 0x00) };
    midi_send(m, 3);
}

/* ---------------------------------------------------------------- sound */

struct voice { int on, rel; float ph, inc, amp; };
static struct voice voices[17];
static float note_freq[16];
static int beep_timer;

static void sound_init(void)
{
    float f = 130.8128f;   /* C3 */
    for (int i = 0; i < 16; i++) {
        note_freq[i] = f;
        f *= 1.0594631f;
    }
}

static void voice_start(int i, float freq, float amp)
{
    voices[i].on = 1;
    voices[i].rel = 0;
    voices[i].ph = 0.0f;
    voices[i].inc = freq / 44100.0f;
    voices[i].amp = amp;
}

static void render(int32_t *out, int frames)
{
    for (int n = 0; n < frames; n++) {
        float s = 0.0f;
        for (int i = 0; i < 17; i++) {
            struct voice *v = &voices[i];
            if (!v->on)
                continue;
            v->ph += v->inc;
            if (v->ph >= 1.0f)
                v->ph -= 1.0f;
            float x = v->ph * 2.0f - 1.0f;                 /* -1..1 */
            float ax = x < 0 ? -x : x;
            float y = 4.0f * x * (1.0f - ax);              /* parabola ~ sine */
            float ay = y < 0 ? -y : y;
            y = 0.225f * (y * ay - y) + y;
            s += y * v->amp;
            v->amp *= v->rel ? 0.9993f : 0.99998f;
            if (v->amp < 0.0005f)
                v->on = 0;
        }
        s *= 0.25f;
        if (s > 0.98f)
            s = 0.98f;
        if (s < -0.98f)
            s = -0.98f;
        int32_t q = (int32_t)(s * 2147483647.0f);
        out[n * 2] = q;
        out[n * 2 + 1] = q;
    }
}

/* ---------------------------------------------------------------- screen */

static void px(int x, int y, uint32_t c)
{
    if (x >= 0 && y >= 0 && x < 320 && y < 240)
        shadow[y * 320 + x] = c;
}

static void rect(int x, int y, int w, int h, uint32_t c)
{
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            px(x + i, y + j, c);
}

static void ch(int x, int y, char c, int sc, uint32_t col)
{
    if (c < 0)
        return;
    for (int cx = 0; cx < 5; cx++) {
        uint8_t bits = FONT[(int)c][cx];
        for (int r = 0; r < 7; r++)
            if ((bits >> r) & 1)
                rect(x + cx * sc, y + r * sc, sc, sc, col);
    }
}

static void text(int x, int y, const char *s, int sc, uint32_t col)
{
    for (; *s; s++, x += 6 * sc)
        ch(x, y, *s, sc, col);
}

#define C_BG 0x0F1620
#define C_TXT 0xE6EDF3
#define C_DIM 0x7C8A99
#define C_ACC 0xFF8A1F
#define C_BAR 0x2E86DE
#define C_PADOFF 0x1B2A3A

static void draw_ui(void)
{
    rect(0, 0, 320, 240, C_BG);
    text(8, 4, "MPC CONSOLE TEST", 2, C_ACC);
    text(8, 22, "SHIFT+STOP = EXIT", 2, C_DIM);

    for (int i = 0; i < 5; i++) {
        int y = 44 + i * 18;
        text(8, y, KNOBNAME[i], 2, C_TXT);
        rect(44, y + 2, 106, 12, C_PADOFF);
        if (knob[i] >= 0) {
            rect(44, y + 2, knob[i] * 106 / 127, 12, C_BAR);
            char t[8];
            sint(t, knob[i]);
            text(156, y, t, 2, C_TXT);
        } else {
            text(156, y, "--", 2, C_DIM);
        }
    }
    {
        char t[24];
        char *p = scat(t, "ENC ");
        if (enc_seen) {
            if (enc_total > 0)
                *p++ = '+';
            sint(p, enc_total);
        } else {
            scat(p, "--");
        }
        text(8, 44 + 5 * 18, t, 2, C_TXT);
    }

    /* pad grid: pads 1-4 are the bottom row, as on the device */
    for (int i = 0; i < 16; i++) {
        int row = i / 4, col = i % 4;
        int x = 220 + col * 24, y = 44 + (3 - row) * 24;
        uint32_t c = C_PADOFF;
        if (pad_down[i]) {
            int b = 0x80 + pad_vel[i];
            if (b > 255)
                b = 255;
            c = ((uint32_t)b << 16) | ((uint32_t)(b * 0x3B / 0x7F + 0x20) << 8);
        }
        rect(x, y, 20, 20, c);
    }

    for (int i = 0; i < 5; i++)
        text(8, 156 + i * 16, logl[i], 2, i == 4 ? C_TXT : C_DIM);
}

/* ---------------------------------------------------------------- events */

static void on_pad(int idx, int vel, int on)
{
    pad_down[idx] = on;
    if (on) {
        pad_vel[idx] = vel;
        voice_start(idx, note_freq[idx], 0.15f + 0.85f * (float)vel / 127.0f);
        int b = 0x30 + vel / 2;
        pad_led(idx, b, b * 0x3B / 0x7F, 0);
        char m[40];
        char *p = scat(m, "PAD ");
        p = sint(p, idx + 1);
        p = scat(p, " VEL ");
        sint(p, vel);
        add_log(m);
    } else {
        voices[idx].rel = 1;
        pad_idle(idx);
    }
    dirty = 1;
}

static void on_note(int chan, int note, int vel, int on)
{
    if (chan == 9) {
        for (int i = 0; i < 16; i++)
            if (PADNOTE[i] == note) {
                on_pad(i, vel, on);
                return;
            }
        char m[40];
        char *p = scat(m, "PAD NOTE ");
        sint(p, note);
        add_log(m);
        return;
    }
    if (chan == 0) {
        const char *name = 0;
        for (int i = 0; i < NBTNS; i++)
            if (BTNS[i].note == note)
                name = BTNS[i].name;
        char m[40];
        char *p = scat(m, "BTN ");
        if (name)
            p = scat(p, name);
        else
            p = shex(p, note);
        scat(p, on ? " DOWN" : " UP");
        add_log(m);
        btn_led(note, on);
        if (note == NOTE_SHIFT)
            shift_down = on;
        if (note == NOTE_STOP && on && shift_down)
            quit = 1;
        return;
    }
    char m[40];
    char *p = scat(m, "NOTE CH");
    p = sint(p, chan + 1);
    p = scat(p, " ");
    sint(p, note);
    add_log(m);
}

static void on_cc(int chan, int cc, int val)
{
    if (chan == 0 && cc >= 0x10 && cc <= 0x14) {
        knob[cc - 0x10] = val;
        dirty = 1;
        return;
    }
    if (chan == 0 && cc == 0x64) {
        enc_seen = 1;
        enc_total += val < 64 ? val : val - 128;
        dirty = 1;
        return;
    }
    char m[40];
    char *p = scat(m, "CC CH");
    p = sint(p, chan + 1);
    p = scat(p, " ");
    p = shex(p, cc);
    p = scat(p, " ");
    sint(p, val);
    add_log(m);
}

/* MIDI byte stream -> messages (running status, SysEx skipped, real-time ignored) */
static void feed(uint8_t b)
{
    static int status, need, have, in_sysex;
    static uint8_t d[2];
    if (b >= 0xF8)
        return;
    if (b >= 0x80) {
        if (b == 0xF0) {
            in_sysex = 1;
            status = 0;
            return;
        }
        if (b == 0xF7) {
            in_sysex = 0;
            return;
        }
        in_sysex = 0;
        status = b;
        have = 0;
        int hi = b & 0xF0;
        need = (hi == 0xC0 || hi == 0xD0) ? 1 : 2;
        return;
    }
    if (in_sysex || !status)
        return;
    d[have++] = b;
    if (have < need)
        return;
    have = 0;
    int hi = status & 0xF0, chan = status & 15;
    if (hi == 0x90)
        on_note(chan, d[0], d[1], d[1] > 0);
    else if (hi == 0x80)
        on_note(chan, d[0], 0, 0);
    else if (hi == 0xB0)
        on_cc(chan, d[0], d[1]);
    /* 0xA0 poly pressure, 0xC0, 0xD0, 0xE0: ignored */
}

#ifndef HOST_TEST
static void on_signal(int s)
{
    (void)s;
    quit = 1;
}
#endif

int main(void)
{
    say("mpc_test: stopping the MPC app...\n");
#ifndef HOST_TEST
    system("systemctl unset-environment LD_PRELOAD");
    system("systemctl stop ac50.service");
    signal(2, on_signal);
    signal(15, on_signal);
#endif
    fb_ok = fb_init();
    audio_ok = audio_init();
    midi_ok = midi_init();
    say(fb_ok ? "screen: ok\n" : "screen: NOT available\n");
    say(audio_ok ? "audio: ok\n" : "audio: NOT available\n");
    say(midi_ok ? "controls: ok\n" : "controls: NOT available\n");

    sound_init();
    for (int i = 0; i < 16; i++)
        pad_idle(i);
    voice_start(16, 880.0f, 0.5f);
    beep_timer = 50;
    add_log("READY - PLAY THE PADS");

    static int32_t frames[128 * 2];
    uint8_t in[64];
    long tick = 0;
    while (!quit) {
#ifdef HOST_TEST
        host_tick = tick;
        host_script(tick);
        if (tick > 400)
            break;
#endif
        int n = midi_ok ? midi_read(in, sizeof in) : 0;
        for (int i = 0; i < n; i++)
            feed(in[i]);
        if (beep_timer && --beep_timer == 0)
            voices[16].rel = 1;
        render(frames, 128);
        if (audio_ok)
            audio_write(frames, 128);
#ifndef HOST_TEST
        else
            usleep(2900);
#endif
        tick++;
        if (tick % 8 == 0 && dirty) {
            draw_ui();
            fb_flush();
            dirty = 0;
        }
    }

    say("mpc_test: leaving, starting the MPC app again...\n");
    for (int i = 0; i < 16; i++)
        pad_led(i, 0, 0, 0);
#ifdef HOST_TEST
    draw_ui();
    fb_flush();
    host_ppm("shot_final.ppm");
    {
        FILE *f = fopen("audio.raw", "wb");
        fwrite(host_audio, sizeof(int32_t), (size_t)host_audio_n, f);
        fclose(f);
    }
    fclose(host_midi_out);
    printf("quit flag %d after %ld ticks\n", (int)quit, tick);
#else
    system("systemctl start ac50.service");
#endif
    return 0;
}
