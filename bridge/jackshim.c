/*
 * jackshim.c - a tiny stand-in for libjack that runs Console's sound core on the Akai MPC Sample.
 *
 * Console's C core (pi-app/core/core.c) dlopen()s a libjack and uses ~15 functions. This library provides
 * exactly those, so the core runs unchanged:
 *     core_open("/path/to/libjack_mpc.so", "console")
 *
 *   audio out      the core's out_L / out_R -> ALSA hw:2,0 (stereo, 44100, S32_LE), 128 frames at a time
 *   audio in       silence for now (in_L / in_R)
 *   controls_in    the MPC's pads / buttons / knobs, turned into the Move's MIDI by mapping.h
 *   lights_out     the Move's pad / button lights, turned into MPC lights by mapping.h
 *   display_out    the Move's 128x64 1-bit screen ("MOVEDISP" + 1024 bytes), drawn 2x on the MPC's 320x240 screen
 *                  (draw_move_display). A native 320x240 interface can replace that one function later.
 *
 * The whole thing runs in one real-time thread (ALSA's blocking write paces it); the screen has its own thread.
 *
 * Built with no ARM headers: see build.sh. Host test: -DHOST_TEST (fake hardware), see test/.
 */
#include <stdint.h>
#include <stddef.h>

#ifdef HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
#include <fcntl.h>
#define EXPORT __attribute__((visibility("default")))
#else
#define EXPORT __attribute__((visibility("default")))
extern int open(const char *, int, ...);
extern int close(int);
extern long read(int, void *, unsigned long);
extern long write(int, const void *, unsigned long);
extern int ioctl(int, unsigned long, ...);
extern long lseek(int, long, int);
extern int usleep(unsigned);
extern int pthread_create(unsigned long *, const void *, void *(*)(void *), void *);
extern int pthread_join(unsigned long, void **);
struct sched_param_ { int prio; };
extern int sched_setscheduler(int, int, const struct sched_param_ *);
extern int snd_pcm_open(void **, const char *, int, int);
extern int snd_pcm_set_params(void *, int, int, unsigned, unsigned, int, unsigned);
extern long snd_pcm_writei(void *, const void *, unsigned long);
extern long snd_pcm_readi(void *, void *, unsigned long);
extern int snd_pcm_recover(void *, int, int);
extern int snd_pcm_close(void *);
extern void *memcpy(void *, const void *, unsigned long);
extern void *memset(void *, int, unsigned long);
extern int memcmp(const void *, const void *, unsigned long);
#endif

#define O_RDWR_ 2
#define O_WRONLY_ 1
#define O_NONBLOCK_ 04000
#define FBIOGET_VSCREENINFO 0x4600
#define FBIOGET_FSCREENINFO 0x4602

#define RATE 44100
#define PERIOD 128
#define NPORTS 8
#define MIDI_STORE 4096
#define MIDI_EVENTS 128

/* ---------------------------------------------------------------- JACK-shaped data */

typedef struct { uint32_t time; size_t size; unsigned char *buffer; } jack_midi_event_t;
typedef int (*JackProcess)(uint32_t, void *);

struct mev { uint32_t time; uint32_t size; uint32_t off; };
struct port {
    char name[32];
    int midi, input, used;
    float audio[PERIOD * 2];
    struct mev ev[MIDI_EVENTS];
    int nev, nstore;
    unsigned char store[MIDI_STORE];
};

static struct port ports[NPORTS];
static int nports;
static JackProcess callback;
static void *callback_arg;
static volatile int running;
static unsigned long audio_thread, display_thread;
static int threads_started;

static int streq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static struct port *find(const char *name)
{
    for (int i = 0; i < nports; i++)
        if (streq(ports[i].name, name)) return &ports[i];
    return 0;
}

/* ---------------------------------------------------------------- hardware (small, replaceable) */

static int midifd = -1, fbfd = -1;
static void *pcm;
static void *pcm_in;                                  /* the capture side (the mic / line inputs) of the same I2S card; NULL = no input */
static uint32_t fbw = 320, fbh = 240, fbstride = 1280, roff = 16, goff = 8, boff = 0;

struct fb_bitfield { uint32_t offset, length, msb_right; };
struct fb_var {
    uint32_t xres, yres, xres_virtual, yres_virtual, xoffset, yoffset, bits_per_pixel, grayscale;
    struct fb_bitfield red, green, blue, transp;
    uint32_t rest[20];
};
struct fb_fix { char id[16]; unsigned long smem_start; uint32_t smem_len, type, type_aux, visual;
                uint16_t xpanstep, ypanstep, ywrapstep; uint32_t line_length; unsigned long mmio_start;
                uint32_t mmio_len, accel; uint16_t caps, reserved[2]; };

#ifdef HOST_TEST
static int host_midi_inject_n;
static unsigned char host_midi_inject[1024];
static pthread_mutex_t host_lock = PTHREAD_MUTEX_INITIALIZER;
static FILE *host_log;
EXPORT void mpcshim_test_inject(const unsigned char *b, int n)
{
    pthread_mutex_lock(&host_lock);
    for (int i = 0; i < n && host_midi_inject_n < 1024; i++) host_midi_inject[host_midi_inject_n++] = b[i];
    pthread_mutex_unlock(&host_lock);
}
EXPORT void mpcshim_test_log(FILE *f) { host_log = f; }
EXPORT uint32_t mpcshim_test_screen[320 * 240];
EXPORT long mpcshim_test_frames;
#endif

static int hw_audio_open(void)
{
#ifdef HOST_TEST
    return 0;
#else
    for (int tries = 0; tries < 25; tries++) {
        if (snd_pcm_open(&pcm, "hw:2,0", 0, 0) == 0) {
            /* S32_LE = 10, RW_INTERLEAVED = 3, stereo, 44100, no resampling, 9 ms buffer */
            if (snd_pcm_set_params(pcm, 10, 3, 2, RATE, 0, 9000) == 0) {
                /* the inputs: SND_PCM_STREAM_CAPTURE = 1; if it can't be opened Console simply hears silence there */
                if (snd_pcm_open(&pcm_in, "hw:2,0", 1, 0) == 0) {
                    if (snd_pcm_set_params(pcm_in, 10, 3, 2, RATE, 0, 9000) != 0) { snd_pcm_close(pcm_in); pcm_in = 0; }
                } else pcm_in = 0;
                return 0;
            }
            snd_pcm_close(pcm);
            return -1;
        }
        usleep(200000);
    }
    return -1;
#endif
}

#ifdef HOST_TEST
EXPORT float mpcshim_test_input = 0.f;                   /* what the fake inputs hear */
#endif

/* one period of the inputs into in_L / in_R (silence when there is no capture device or it failed) */
static void hw_audio_read(float *l, float *r)
{
#ifdef HOST_TEST
    for (int i = 0; i < PERIOD; i++) l[i] = r[i] = mpcshim_test_input;
#else
    static int32_t in32[PERIOD * 2];
    if (!pcm_in) return;
    long got = 0;
    int fails = 0;
    while (got < PERIOD) {
        long k = snd_pcm_readi(pcm_in, in32 + got * 2, (unsigned long)(PERIOD - got));
        if (k < 0) {
            if (snd_pcm_recover(pcm_in, (int)k, 1) < 0 || ++fails > 3) {      /* a persistent error: the inputs stay silent */
                if (fails > 3) pcm_in = 0;
                break;
            }
            continue;
        }
        got += k;
    }
    for (int i = 0; i < got; i++) {
        l[i] = (float)in32[i * 2] * (1.0f / 2147483648.0f);
        r[i] = (float)in32[i * 2 + 1] * (1.0f / 2147483648.0f);
    }
#endif
}

static void hw_audio_write(const int32_t *fr, int n)
{
#ifdef HOST_TEST
    (void)fr; (void)n;
    mpcshim_test_frames += n;
    usleep(2900);
#else
    while (n > 0) {
        long r = snd_pcm_writei(pcm, fr, (unsigned long)n);
        if (r < 0) {
            if (snd_pcm_recover(pcm, (int)r, 1) < 0) return;
            continue;
        }
        fr += r * 2;
        n -= (int)r;
    }
#endif
}

static void dbg(char dir, const uint8_t *b, int n);

static int hw_midi_open(void)
{
#ifdef HOST_TEST
    return 0;
#else
    for (int tries = 0; tries < 25; tries++) {
        midifd = open("/dev/snd/midiC0D0", O_RDWR_ | O_NONBLOCK_);
        if (midifd >= 0) {
            /* The stock app asks for timestamped records (32-byte frames) and the kernel remembers that after it
               stops. We want plain MIDI bytes: SNDRV_RAWMIDI_IOCTL_PARAMS, stream = input, mode = 0 (no framing). */
            uint64_t p[6];
            memset(p, 0, sizeof p);
            ((int *)p)[0] = 1;            /* stream: input */
            p[1] = 4096;                  /* buffer_size */
            p[2] = 1;                     /* avail_min */
            int r = ioctl(midifd, 0xC0305710UL, p);
            if (r != 0) { uint8_t e = (uint8_t)(-r); dbg('E', &e, 1); }
            return 0;
        }
        usleep(200000);
    }
    return -1;
#endif
}

/* Debug log: only if the file /tmp/mpcbridge.log exists (touch it first). Lines: "I <hex bytes>" from the MPC, "O <hex bytes>" to it. */
#ifndef HOST_TEST
static int dbgfd = -2;
static void dbg(char dir, const uint8_t *b, int n)
{
    if (dbgfd == -2) dbgfd = open("/tmp/mpcbridge.log", O_WRONLY_ | 02000);
    if (dbgfd < 0) return;
    char line[200];
    int k = 0;
    line[k++] = dir;
    for (int i = 0; i < n && k < 190; i++) {
        static const char hx[] = "0123456789ABCDEF";
        line[k++] = ' '; line[k++] = hx[b[i] >> 4]; line[k++] = hx[b[i] & 15];
    }
    line[k++] = '\n';
    write(dbgfd, line, (unsigned long)k);
}
#else
static void dbg(char dir, const uint8_t *b, int n) { (void)dir; (void)b; (void)n; }
#endif

static int hw_midi_read(uint8_t *b, int max)
{
#ifdef HOST_TEST
    pthread_mutex_lock(&host_lock);
    int n = host_midi_inject_n < max ? host_midi_inject_n : max;
    memcpy(b, host_midi_inject, (size_t)n);
    memmove(host_midi_inject, host_midi_inject + n, (size_t)(host_midi_inject_n - n));
    host_midi_inject_n -= n;
    pthread_mutex_unlock(&host_lock);
    return n;
#else
    long r = read(midifd, b, (unsigned long)max);
    if (r > 0) dbg('I', b, (int)r);
    return r > 0 ? (int)r : 0;
#endif
}

static void hw_midi_write(const uint8_t *b, int n)
{
#ifdef HOST_TEST
    if (host_log) {
        fputs("MPC<- ", host_log);
        for (int i = 0; i < n; i++) fprintf(host_log, "%02X ", b[i]);
        fputc('\n', host_log);
    }
#else
    dbg('O', b, n);
    int off = 0, spins = 0;
    while (off < n && spins < 200) {
        long r = write(midifd, b + off, (unsigned long)(n - off));
        if (r > 0) off += (int)r;
        else { usleep(300); spins++; }
    }
#endif
}

static int hw_fb_open(void)
{
#ifdef HOST_TEST
    return 0;
#else
    fbfd = open("/dev/fb0", O_RDWR_);
    if (fbfd < 0) return -1;
    struct fb_var v;
    struct fb_fix f;
    if (ioctl(fbfd, FBIOGET_VSCREENINFO, &v) == 0) {
        if (v.xres != 320 || v.yres != 240 || v.bits_per_pixel != 32) { close(fbfd); fbfd = -1; return -1; }
        roff = v.red.offset; goff = v.green.offset; boff = v.blue.offset;
    }
    fbstride = 1280;
    if (ioctl(fbfd, FBIOGET_FSCREENINFO, &f) == 0 && f.line_length) fbstride = f.line_length;
    int b = open("/sys/class/graphics/fb0/blank", O_WRONLY_);
    if (b >= 0) { write(b, "1", 1); write(b, "0", 1); close(b); }
    return 0;
#endif
}

/* ---------------------------------------------------------------- the host side of mapping.h */

#include "mapping.h"

#define PEND 256
static uint8_t pend[PEND][3];
static int npend;

static void to_console(const uint8_t *m, int n)
{
    if (npend >= PEND || n != 3) return;
    pend[npend][0] = m[0]; pend[npend][1] = m[1]; pend[npend][2] = m[2];
    npend++;
}

static void mpc_pad_light(int pad, int r, int g, int b)
{
    uint8_t m[12] = { 0xF0, 0x47, 0x7F, 0x5C, 0x65, 0x00, 0x04, (uint8_t)pad, (uint8_t)r, (uint8_t)g, (uint8_t)b, 0xF7 };
    hw_midi_write(m, 12);
}

static void mpc_btn_light(int note, int on)
{
    uint8_t m[3] = { 0xB0, (uint8_t)note, (uint8_t)(on ? 0x02 : 0x00) };   /* 0 off, 1 lit, 2 brighter (7F is not "on" for most buttons) */
    hw_midi_write(m, 3);
}

/* ---------------------------------------------------------------- the screen */

/* The Move's screen as Console draws it: "MOVEDISP" + 1024 bytes, 8 strips of 128 bytes, bit 0 = top.
   Latest frame is handed to the screen thread; it never blocks the audio thread. */
static uint8_t frame[2][1024];
static volatile int frame_new = -1, frame_busy, frame_last = -1;
static uint32_t shadow[320 * 240], outbuf[320 * 240];

/* THE place to swap in a native 320x240 interface: this turns the Move's 1-bit screen into pixels.
   Today: each Move pixel becomes a 2x2 square, centred (256x128 of the 320x240). */
static void draw_move_display(const uint8_t *d)
{
    const uint32_t on = 0x00F2EBDD, off = 0x00000000;
    for (int y = 0; y < 128; y++) {
        for (int x = 0; x < 256; x++) {
            int sx = x / 2, sy = y / 2;
            int bit = (d[(sy / 8) * 128 + sx] >> (sy & 7)) & 1;
            shadow[(56 + y) * 320 + 32 + x] = bit ? on : off;
        }
    }
}

static void fb_flush(void)
{
#ifndef HOST_TEST
    if (fbfd < 0) return;
#endif
    for (uint32_t i = 0; i < 320 * 240; i++) {
        uint32_t c = shadow[i];
        outbuf[i] = (((c >> 16) & 255) << roff) | (((c >> 8) & 255) << goff) | ((c & 255) << boff);
    }
#ifdef HOST_TEST
    memcpy(mpcshim_test_screen, shadow, sizeof shadow);
#else
    if (fbstride == 1280) {
        lseek(fbfd, 0, 0);
        write(fbfd, outbuf, 320 * 240 * 4);
    } else {
        for (uint32_t y = 0; y < 240; y++) {
            lseek(fbfd, (long)(y * fbstride), 0);
            write(fbfd, &outbuf[y * 320], 320 * 4);
        }
    }
#endif
}

/* A native 320x240 screen from Console (mpcui/native.py): the file /tmp/console-native.rgb = "CNAT", a 32-bit counter,
   then 320*240 RGB bytes. Present = it is the screen (the Move's 1-bit frames are ignored); absent = the scaled Move screen. */
#define NATIVE_PATH "/tmp/console-native.rgb"
static uint32_t native_seq = 0xFFFFFFFFu;
static uint8_t nbuf[8 + 320 * 240 * 3];

static int was_native;

/* /tmp/console-pagemode: one letter from Console: T = the tape page (the pads are the step buttons there), anything else = not */
static void pagemode_poll(void)
{
    int fd = open("/tmp/console-pagemode", 0);
    if (fd < 0) { page_tape = 0; page_param = 0; return; }
    char ch = 0;
    long n = read(fd, &ch, 1);
    close(fd);
    if (n == 1) { page_tape = (ch == 'T'); page_param = (ch == 'P'); }
}

static int native_poll(void)
{
    int fd = open(NATIVE_PATH, 0);
    if (fd < 0) { native_seq = 0xFFFFFFFFu; return 0; }
    long n = read(fd, nbuf, 8);
    if (n != 8 || memcmp(nbuf, "CNAT", 4) != 0) { close(fd); return 0; }
    uint32_t seq;
    memcpy(&seq, nbuf + 4, 4);
    if (seq != native_seq) {
        long got = 0;
        while (got < 320 * 240 * 3) {
            long r = read(fd, nbuf + 8 + got, (unsigned long)(320 * 240 * 3 - got));
            if (r <= 0) break;
            got += r;
        }
        if (got == 320 * 240 * 3) {
            for (int i = 0; i < 320 * 240; i++)
                shadow[i] = ((uint32_t)nbuf[8 + i * 3] << 16) | ((uint32_t)nbuf[9 + i * 3] << 8) | nbuf[10 + i * 3];
            native_seq = seq;
            fb_flush();
        }
    }
    close(fd);
    return 1;
}

static void *display_main(void *arg)
{
    (void)arg;
    while (running) {
        pagemode_poll();
        if (native_poll()) { frame_new = -1; was_native = 1; usleep(16000); continue; }
        if (was_native) { was_native = 0; memset(shadow, 0, sizeof shadow); if (frame_last >= 0) frame_new = frame_last; }     /* back to the Move screen */
        int f = frame_new;
        if (f >= 0) {
            frame_busy = f;
            frame_new = -1;
            draw_move_display(frame[f]);
            fb_flush();
        }
        usleep(16000);
    }
    return 0;
}

/* ---------------------------------------------------------------- the audio thread */

static int32_t outbuf32[PERIOD * 2];

static void handle_outputs(void)
{
    struct port *lights = find("lights_out"), *disp = find("display_out");
    if (lights) {
        for (int i = 0; i < lights->nev; i++)
            lights_from_console(lights->store + lights->ev[i].off, (int)lights->ev[i].size);
    }
    if (disp) {
        for (int i = 0; i < disp->nev; i++) {
            if (disp->ev[i].size == 1032 && memcmp(disp->store + disp->ev[i].off, "MOVEDISP", 8) == 0) {
                int slot = frame_busy ? 0 : 1;
                memcpy(frame[slot], disp->store + disp->ev[i].off + 8, 1024);
                frame_last = slot;
                frame_new = slot;
            }
        }
    }
}

static void *audio_main(void *arg)
{
    (void)arg;
#ifndef HOST_TEST
    struct sched_param_ sp = { 80 };
    sched_setscheduler(0, 1, &sp);                       /* SCHED_FIFO; fine if it is refused */
#endif
    struct port *cin = find("controls_in"), *ol = find("out_L"), *orr = find("out_R");
    struct port *il = find("in_L"), *ir = find("in_R");
    mapping_init();
    while (running) {
        uint8_t raw[64];
        int n;
        while ((n = hw_midi_read(raw, sizeof raw)) > 0)
            for (int i = 0; i < n; i++) mpc_midi_byte(raw[i]);
        mapping_tick();

        if (il) memset(il->audio, 0, sizeof il->audio);
        if (ir) memset(ir->audio, 0, sizeof ir->audio);
        if (il && ir) hw_audio_read(il->audio, ir->audio);
        for (int i = 0; i < nports; i++)
            if (ports[i].midi && !ports[i].input) { ports[i].nev = 0; ports[i].nstore = 0; }
        if (cin) {
            cin->nev = 0; cin->nstore = 0;
            for (int i = 0; i < npend && cin->nev < MIDI_EVENTS; i++) {
                struct mev *e = &cin->ev[cin->nev++];
                e->time = 0; e->size = 3; e->off = (uint32_t)cin->nstore;
                memcpy(cin->store + cin->nstore, pend[i], 3);
                cin->nstore += 3;
            }
            npend = 0;
        }
        if (callback) callback(PERIOD, callback_arg);
        handle_outputs();

        for (int i = 0; i < PERIOD; i++) {
            float l = ol ? ol->audio[i] : 0, r = orr ? orr->audio[i] : 0;
            if (l > 1.f) l = 1.f; else if (l < -1.f) l = -1.f;
            if (r > 1.f) r = 1.f; else if (r < -1.f) r = -1.f;
            outbuf32[i * 2] = (int32_t)(l * 2147483520.f);
            outbuf32[i * 2 + 1] = (int32_t)(r * 2147483520.f);
        }
        hw_audio_write(outbuf32, PERIOD);
    }
    return 0;
}

/* ---------------------------------------------------------------- the JACK functions Console's core uses */

EXPORT void *jack_client_open(const char *name, int options, int *status, ...)
{
    (void)name; (void)options;
    if (status) *status = 0;
    nports = 0;
    memset(ports, 0, sizeof ports);
    return (void *)&ports[0];                            /* any non-NULL handle */
}

EXPORT int jack_client_close(void *c) { (void)c; return 0; }

EXPORT void *jack_port_register(void *c, const char *name, const char *type, unsigned long flags, unsigned long bs)
{
    (void)c; (void)bs;
    if (nports >= NPORTS) return 0;
    struct port *p = &ports[nports++];
    int i = 0;
    while (name[i] && i < 31) { p->name[i] = name[i]; i++; }
    p->name[i] = 0;
    p->midi = type[0] == '8';                           /* "8 bit raw midi" vs "32 bit float mono audio" */
    p->input = (flags & 1) != 0;
    p->used = 1;
    return p;
}

EXPORT void *jack_port_get_buffer(void *p, uint32_t n)
{
    (void)n;
    struct port *q = p;
    return q->midi ? (void *)q : (void *)q->audio;
}

EXPORT int jack_set_process_callback(void *c, JackProcess cb, void *arg)
{
    (void)c;
    callback = cb; callback_arg = arg;
    return 0;
}

EXPORT int jack_connect(void *c, const char *a, const char *b) { (void)c; (void)a; (void)b; return 0; }
EXPORT uint32_t jack_get_sample_rate(void *c) { (void)c; return RATE; }
EXPORT uint32_t jack_get_buffer_size(void *c) { (void)c; return PERIOD; }
EXPORT float jack_cpu_load(void *c) { (void)c; return 0.f; }

EXPORT uint32_t jack_midi_get_event_count(void *b) { return (uint32_t)((struct port *)b)->nev; }

EXPORT int jack_midi_event_get(jack_midi_event_t *ev, void *b, uint32_t i)
{
    struct port *p = b;
    if ((int)i >= p->nev) return -1;
    ev->time = p->ev[i].time;
    ev->size = p->ev[i].size;
    ev->buffer = p->store + p->ev[i].off;
    return 0;
}

EXPORT void jack_midi_clear_buffer(void *b)
{
    struct port *p = b;
    p->nev = 0;
    p->nstore = 0;
}

EXPORT int jack_midi_event_write(void *b, uint32_t time, const unsigned char *data, size_t size)
{
    struct port *p = b;
    if (p->nev >= MIDI_EVENTS || p->nstore + (int)size > MIDI_STORE) return -1;
    struct mev *e = &p->ev[p->nev++];
    e->time = time; e->size = (uint32_t)size; e->off = (uint32_t)p->nstore;
    memcpy(p->store + p->nstore, data, size);
    p->nstore += (int)size;
    return 0;
}

EXPORT int jack_activate(void *c)
{
    (void)c;
    if (threads_started) return 0;
    if (hw_audio_open() != 0) return -1;
    if (hw_midi_open() != 0) return -2;
    hw_fb_open();                                        /* no screen is not fatal */
    running = 1;
#ifdef HOST_TEST
    pthread_t a, d;
    pthread_create(&a, 0, audio_main, 0);
    pthread_create(&d, 0, display_main, 0);
    audio_thread = (unsigned long)a;
    display_thread = (unsigned long)d;
#else
    if (pthread_create(&audio_thread, 0, audio_main, 0)) return -3;
    pthread_create(&display_thread, 0, display_main, 0);
#endif
    threads_started = 1;
    return 0;
}

EXPORT int jack_deactivate(void *c)
{
    (void)c;
    if (!threads_started) return 0;
    running = 0;
#ifdef HOST_TEST
    pthread_join((pthread_t)audio_thread, 0);
    pthread_join((pthread_t)display_thread, 0);
#else
    pthread_join(audio_thread, 0);
    pthread_join(display_thread, 0);
#endif
    threads_started = 0;
    for (int i = 0; i < 16; i++) mpc_pad_light(i, 0, 0, 0);
    return 0;
}
