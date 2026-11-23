/*
 * screenrec.h - the screen recorder (included by jackshim.c).
 *
 * Console turns it on by writing a folder's path into /tmp/console-rec (mpcui/screenrec.py) and off by removing the file.
 * While it is on, three files are written into that folder, all on one clock (CLOCK_MONOTONIC, nanoseconds):
 *
 *   screen.cvr     every frame the screen shows: "CVR1", width, height (16 bits each), then one record per frame:
 *                  'F', time (64 bits), number of runs (32), then each run: first pixel (32), pixel count (32), RGB bytes.
 *                  The first frame is whole; after that only the pixels that changed (nearby changes are merged into one run).
 *   audio.wav      what you hear (Console's output, after the metronome): 32-bit float, stereo, 44100 Hz.
 *   controls.txt   every message from the control panel (pads, buttons, knobs, wheel, fader): "time byte byte ...", in hex.
 *   timing.txt     when the audio starts, and anything that was dropped (written when the recording ends).
 *
 * tools/screenrec-convert.py (on a Mac) turns these into a video and a controls file for After Effects.
 *
 * Nothing here runs in the audio thread except two small copies into memory (rec_audio, rec_midi); the writing to the card
 * is done by a thread of its own (rec_main) at normal priority, so a slow card can't make the sound stutter. If the card can't
 * keep up, frames are skipped first (counted in timing.txt); audio is kept whole (silence is written for anything lost, so it
 * stays in sync).
 */

#define REC_CTL "/tmp/console-rec"
#define REC_ARING (1 << 18)                   /* stereo frames in the audio ring (about 6 seconds) */
#define REC_MRING 1024                        /* panel messages in the controls ring */
#define REC_FSLOTS 4                          /* frames waiting to be written */
#define O_REC_NEW 01101                       /* O_WRONLY | O_CREAT | O_TRUNC */

#ifndef HOST_TEST
extern int fsync(int);
#endif

static volatile int rec_want, rec_on, rec_fail; /* rec_want: set by the screen thread from /tmp/console-rec; rec_on: files open; rec_fail: the folder can't be written (tried again once the file is removed and made again) */
static char rec_dir[512];
static int rec_fd_v = -1, rec_fd_a = -1, rec_fd_c = -1;

static float rec_aring[REC_ARING * 2];
static volatile unsigned rec_aw, rec_ar;      /* audio: written by the audio thread, read by rec_main */
static volatile long long rec_a_t0;           /* when the first recorded audio frame was made */
static volatile unsigned long long rec_a_lost;

struct rec_msg { long long t; unsigned char n; unsigned char b[47]; };
static struct rec_msg rec_mring[REC_MRING];
static volatile unsigned rec_mw, rec_mr;

static uint8_t rec_frames[REC_FSLOTS][320 * 240 * 3];
static long long rec_ftime[REC_FSLOTS];
static volatile unsigned rec_fw, rec_fr;      /* frames: written by the screen thread */
static unsigned long rec_f_dropped, rec_f_written;
static uint8_t rec_prev[320 * 240 * 3];
static int rec_have_prev;
static unsigned long rec_thread;
static int rec_thread_started;
static volatile int rec_kick;                 /* set when a recording starts: the screen thread records what is showing now */

static long long rec_now(void)
{
    struct mts ts;
    mpc_clock(1, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

/* ---- the audio thread: copy one block (already clipped to -1..1) */
static void rec_audio(const float *l, const float *r, int n)
{
    if (!rec_on) return;
    unsigned w = __atomic_load_n(&rec_aw, __ATOMIC_RELAXED), rd = __atomic_load_n(&rec_ar, __ATOMIC_ACQUIRE);
    if (w == 0 && rec_a_t0 == 0) rec_a_t0 = rec_now();
    if (REC_ARING - (w - rd) < (unsigned)n) { rec_a_lost += (unsigned)n; return; }       /* the card is far behind: count it */
    for (int i = 0; i < n; i++) {
        unsigned k = (w + (unsigned)i) & (REC_ARING - 1);
        rec_aring[k * 2] = l ? l[i] : 0.f;
        rec_aring[k * 2 + 1] = r ? r[i] : 0.f;
    }
    __atomic_store_n(&rec_aw, w + (unsigned)n, __ATOMIC_RELEASE);
}

/* ---- the audio thread: one read from the panel (raw MIDI bytes, as they came) */
static void rec_midi(const uint8_t *b, int n)
{
    if (!rec_on || n <= 0) return;
    long long t = rec_now();
    while (n > 0) {
        unsigned w = __atomic_load_n(&rec_mw, __ATOMIC_RELAXED), rd = __atomic_load_n(&rec_mr, __ATOMIC_ACQUIRE);
        if (w - rd >= REC_MRING) return;
        struct rec_msg *m = &rec_mring[w & (REC_MRING - 1)];
        int k = n > 47 ? 47 : n;
        m->t = t; m->n = (unsigned char)k;
        memcpy(m->b, b, (unsigned long)k);
        __atomic_store_n(&rec_mw, w + 1, __ATOMIC_RELEASE);
        b += k; n -= k;
    }
}

/* ---- the screen thread: the frame just shown (shadow: 0x00RRGGBB per pixel) */
static void rec_frame(const uint32_t *px)
{
    if (!rec_on) return;
    unsigned w = rec_fw, rd = __atomic_load_n(&rec_fr, __ATOMIC_ACQUIRE);
    if (w - rd >= REC_FSLOTS) { rec_f_dropped++; return; }
    uint8_t *o = rec_frames[w % REC_FSLOTS];
    for (int i = 0; i < 320 * 240; i++) {
        uint32_t c = px[i];
        o[i * 3] = (uint8_t)(c >> 16); o[i * 3 + 1] = (uint8_t)(c >> 8); o[i * 3 + 2] = (uint8_t)c;
    }
    rec_ftime[w % REC_FSLOTS] = rec_now();
    __atomic_store_n(&rec_fw, w + 1, __ATOMIC_RELEASE);
}

/* ---- the screen thread: is /tmp/console-rec there? (its text is the folder) */
static void rec_poll(void)
{
    if (rec_on && rec_kick) { rec_kick = 0; rec_frame(shadow); }  /* the first frame: the screen as it is (it may not change for a while) */
    int fd = open(REC_CTL, 0);
    if (fd < 0) { rec_want = 0; rec_fail = 0; return; }
    if (!rec_want && !rec_on && !rec_fail) {
        char b[sizeof rec_dir];
        long n = read(fd, b, sizeof b - 1);
        while (n > 0 && (b[n - 1] == '\n' || b[n - 1] == ' ')) n--;
        if (n > 0) { memcpy(rec_dir, b, (unsigned long)n); rec_dir[n] = 0; rec_want = 1; }
    }
    close(fd);
}

/* ---- the writer (rec_main): small helpers with no libc formatting */
static int rec_open(const char *name)
{
    char p[sizeof rec_dir + 32];
    int i = 0, j = 0;
    while (rec_dir[i] && i < (int)sizeof rec_dir - 1) { p[i] = rec_dir[i]; i++; }
    p[i++] = '/';
    while (name[j]) p[i++] = name[j++];
    p[i] = 0;
    return open(p, O_REC_NEW, 0644);
}

static void rec_put(int fd, const void *b, unsigned long n)
{
    const uint8_t *p = b;
    while (n > 0 && fd >= 0) {
        long k = write(fd, p, n);
        if (k <= 0) return;
        p += k; n -= (unsigned long)k;
    }
}

static int rec_dec(char *o, unsigned long long v)
{
    char t[24]; int n = 0, k = 0;
    do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) o[k++] = t[--n];
    return k;
}

static void rec_u32(uint8_t *o, uint32_t v) { o[0] = (uint8_t)v; o[1] = (uint8_t)(v >> 8); o[2] = (uint8_t)(v >> 16); o[3] = (uint8_t)(v >> 24); }
static void rec_u64(uint8_t *o, unsigned long long v) { rec_u32(o, (uint32_t)v); rec_u32(o + 4, (uint32_t)(v >> 32)); }

static unsigned long long rec_a_frames;

static void rec_wav_header(unsigned long long frames)
{
    uint8_t h[58];
    unsigned long long data = frames * 8;
    if (data > 0xFFFFFFF0ULL) data = 0xFFFFFFF0ULL;
    memcpy(h, "RIFF", 4); rec_u32(h + 4, (uint32_t)(50 + data)); memcpy(h + 8, "WAVE", 4);
    memcpy(h + 12, "fmt ", 4); rec_u32(h + 16, 18);
    h[20] = 3; h[21] = 0;                                     /* IEEE float */
    h[22] = 2; h[23] = 0;                                     /* stereo */
    rec_u32(h + 24, RATE); rec_u32(h + 28, RATE * 8);
    h[32] = 8; h[33] = 0; h[34] = 32; h[35] = 0; h[36] = 0; h[37] = 0;
    memcpy(h + 38, "fact", 4); rec_u32(h + 42, 4); rec_u32(h + 46, (uint32_t)frames);
    memcpy(h + 50, "data", 4); rec_u32(h + 54, (uint32_t)data);
    lseek(rec_fd_a, 0, 0);
    rec_put(rec_fd_a, h, 58);
    lseek(rec_fd_a, 0, 2);
}

static void rec_start(void)
{
    rec_fd_v = rec_open("screen.cvr");
    rec_fd_a = rec_open("audio.wav");
    rec_fd_c = rec_open("controls.txt");
    if (rec_fd_v < 0 || rec_fd_a < 0 || rec_fd_c < 0) {
        if (rec_fd_v >= 0) close(rec_fd_v);
        if (rec_fd_a >= 0) close(rec_fd_a);
        if (rec_fd_c >= 0) close(rec_fd_c);
        rec_fd_v = rec_fd_a = rec_fd_c = -1;
        rec_fail = 1;
        rec_want = 0;
        return;
    }
    uint8_t h[8] = { 'C', 'V', 'R', '1', 320 & 255, 320 >> 8, 240, 0 };
    rec_put(rec_fd_v, h, 8);
    rec_a_frames = 0;
    rec_wav_header(0);
    rec_aw = rec_ar = 0; rec_mw = rec_mr = 0; rec_fw = rec_fr = 0;
    rec_a_t0 = 0; rec_a_lost = 0; rec_f_dropped = rec_f_written = 0; rec_have_prev = 0;
    rec_kick = 1;
    __atomic_store_n(&rec_on, 1, __ATOMIC_RELEASE);
}

/* write what is waiting; returns 1 if there was anything */
static uint8_t rec_vbuf[8 + 320 * 240 * 3 + 64 * 1024];
static int rec_drain(void)
{
    int did = 0;
    /* audio */
    unsigned w = __atomic_load_n(&rec_aw, __ATOMIC_ACQUIRE), rd = rec_ar;
    while (w != rd) {
        unsigned k = rd & (REC_ARING - 1), n = w - rd;
        if (n > REC_ARING - k) n = REC_ARING - k;                 /* up to the end of the ring */
        rec_put(rec_fd_a, &rec_aring[k * 2], (unsigned long)n * 8);
        rec_a_frames += n; rd += n; did = 1;
        __atomic_store_n(&rec_ar, rd, __ATOMIC_RELEASE);
    }
    /* the panel */
    {
        char line[64 + 47 * 3];
        unsigned mw = __atomic_load_n(&rec_mw, __ATOMIC_ACQUIRE), mr = rec_mr;
        while (mw != mr) {
            struct rec_msg *m = &rec_mring[mr & (REC_MRING - 1)];
            int k = rec_dec(line, (unsigned long long)m->t);
            for (int i = 0; i < m->n; i++) {
                static const char hx[] = "0123456789abcdef";
                line[k++] = ' '; line[k++] = hx[m->b[i] >> 4]; line[k++] = hx[m->b[i] & 15];
            }
            line[k++] = '\n';
            rec_put(rec_fd_c, line, (unsigned long)k);
            mr++; did = 1;
            __atomic_store_n(&rec_mr, mr, __ATOMIC_RELEASE);
        }
    }
    /* the screen: only what changed since the last frame (runs closer than 16 pixels are one run) */
    unsigned fw = __atomic_load_n(&rec_fw, __ATOMIC_ACQUIRE), fr = rec_fr;
    while (fw != fr) {
        const uint8_t *f = rec_frames[fr % REC_FSLOTS];
        long long t = rec_ftime[fr % REC_FSLOTS];
        unsigned long o = 1 + 8 + 4;                             /* 'F', time, number of runs (filled in below) */
        uint32_t runs = 0;
        int i = 0, N = 320 * 240;
        while (i < N) {
            if (rec_have_prev && memcmp(f + i * 3, rec_prev + i * 3, 3) == 0) { i++; continue; }
            int s = i, e = i + 1, gap = 0;
            while (e < N && gap < 16) {
                if (!rec_have_prev || memcmp(f + e * 3, rec_prev + e * 3, 3) != 0) gap = 0; else gap++;
                e++;
            }
            int len = e - gap - s;
            if (o + 8 + (unsigned long)len * 3 > sizeof rec_vbuf) break;
            rec_u32(rec_vbuf + o, (uint32_t)s); rec_u32(rec_vbuf + o + 4, (uint32_t)len);
            memcpy(rec_vbuf + o + 8, f + s * 3, (unsigned long)len * 3);
            o += 8 + (unsigned long)len * 3;
            runs++;
            i = s + len;
        }
        if (runs || !rec_have_prev) {
            rec_vbuf[0] = 'F';
            rec_u64(rec_vbuf + 1, (unsigned long long)t);
            rec_u32(rec_vbuf + 9, runs);
            rec_put(rec_fd_v, rec_vbuf, o);
            rec_f_written++;
        }
        memcpy(rec_prev, f, sizeof rec_prev);
        rec_have_prev = 1;
        fr++; did = 1;
        __atomic_store_n(&rec_fr, fr, __ATOMIC_RELEASE);
    }
    return did;
}

static void rec_stop(void)
{
    __atomic_store_n(&rec_on, 0, __ATOMIC_RELEASE);
    usleep(20000);                                               /* (a block that had already started copying finishes) */
    while (rec_drain()) {}
    if (rec_a_lost) {                                           /* keep the audio's length true: silence for what was lost */
        static const float z[256];
        unsigned long long left = rec_a_lost;
        while (left) { unsigned long k = left > 128 ? 128 : (unsigned long)left; rec_put(rec_fd_a, z, k * 8); rec_a_frames += k; left -= k; }
    }
    rec_wav_header(rec_a_frames);
    int fd = rec_open("timing.txt");
    if (fd >= 0) {
        char b[256]; int k = 0;
        static const char a[] = "audio_start_ns ", f1[] = "\naudio_frames ", f2[] = "\naudio_lost_frames ", f3[] = "\nframes_written ", f4[] = "\nframes_dropped ";
        memcpy(b + k, a, sizeof a - 1); k += sizeof a - 1; k += rec_dec(b + k, (unsigned long long)rec_a_t0);
        memcpy(b + k, f1, sizeof f1 - 1); k += sizeof f1 - 1; k += rec_dec(b + k, rec_a_frames);
        memcpy(b + k, f2, sizeof f2 - 1); k += sizeof f2 - 1; k += rec_dec(b + k, rec_a_lost);
        memcpy(b + k, f3, sizeof f3 - 1); k += sizeof f3 - 1; k += rec_dec(b + k, rec_f_written);
        memcpy(b + k, f4, sizeof f4 - 1); k += sizeof f4 - 1; k += rec_dec(b + k, rec_f_dropped);
        b[k++] = '\n';
        rec_put(fd, b, (unsigned long)k);
        fsync(fd); close(fd);
    }
    fsync(rec_fd_v); fsync(rec_fd_a); fsync(rec_fd_c);
    close(rec_fd_v); close(rec_fd_a); close(rec_fd_c);
    rec_fd_v = rec_fd_a = rec_fd_c = -1;
}

static void *rec_main(void *arg)
{
    (void)arg;
    while (running || rec_on) {
        if (rec_want && !rec_on) rec_start();
        if (rec_on && (!rec_want || !running)) rec_stop();
        if (rec_on) rec_drain();
        usleep(rec_on ? 10000 : 50000);
    }
    return 0;
}
