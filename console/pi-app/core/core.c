/* Console's sound core: a JACK client whose process callback makes the sound, 128 frames at a time.
 *
 * No Python runs in the audio path. Python (core.py) sets it up and talks to it through:
 *   - sources: the instruments. Each is an "engine" (a library with render(float *out, n) writing n frames of
 *     `voices` interleaved channels, and trigger(voice, velocity)) or a Schwung "module" instance (rendered by
 *     the host's sh_render(inst, out, n) as stereo, played with sh_midi(inst, b0, b1, b2)). Python loads the
 *     libraries and hands over the function addresses.
 *   - an event queue (Python -> core): hits, MIDI and calls into a library (parameter changes), each with the
 *     frame it should happen at, so they land on the exact sample.
 *   - the Move's controls (core -> Python): MIDI from the pads, knobs and buttons, queued for Python to read.
 *   - lights and the screen (Python -> core): MIDI out and display frames, sent in the next cycle.
 *   - mixing settings (pans, sends, gains) in plain memory Python can write any time.
 *
 * libjack is opened at run time (dlopen), from the path Python gives: on the Move that's RNBO's own copy,
 * which has to match the JACK server it starts.
 */
#include <dlfcn.h>
#include <math.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(__SSE__)
#include <xmmintrin.h>
#endif

/* ------------------------------------------------------------------ JACK, opened at run time */

typedef uint32_t jack_nframes_t;
typedef struct { jack_nframes_t time; size_t size; unsigned char *buffer; } jack_midi_event_t;
typedef int (*JackProcess)(jack_nframes_t, void *);

static struct {
    void *(*client_open)(const char *, int, int *, ...);
    int (*client_close)(void *);
    int (*activate)(void *);
    int (*deactivate)(void *);
    void *(*port_register)(void *, const char *, const char *, unsigned long, unsigned long);
    void *(*port_get_buffer)(void *, jack_nframes_t);
    int (*set_process_callback)(void *, JackProcess, void *);
    int (*connect)(void *, const char *, const char *);
    jack_nframes_t (*get_sample_rate)(void *);
    jack_nframes_t (*get_buffer_size)(void *);
    uint32_t (*midi_get_event_count)(void *);
    int (*midi_event_get)(jack_midi_event_t *, void *, uint32_t);
    void (*midi_clear_buffer)(void *);
    int (*midi_event_write)(void *, jack_nframes_t, const unsigned char *, size_t);
    float (*cpu_load)(void *);
} J;

static const char *AUDIO = "32 bit float mono audio", *MIDI = "8 bit raw midi";
enum { IS_INPUT = 1, IS_OUTPUT = 2, NO_START_SERVER = 1 };

/* ------------------------------------------------------------------ sources */

#define MAX_SOURCES 24
#define MAX_VOICES 16
#define MAX_BLOCK 4096
#define TAIL (8 * 44100)                      /* a source sleeps this long after its last note or hit */

enum { ENGINE = 1, MODULE = 2 };

typedef struct {
    int kind, voices;                         /* 0 kind: slot unused */
    void (*render)(float *, int);             /* ENGINE */
    void (*trigger)(int, int);
    void *inst;                               /* MODULE */
    void (*sh_render)(void *, float *, int);
    void (*sh_midi)(void *, int, int, int);
    float pan[MAX_VOICES][2];                 /* each voice's left / right gain (Python sets them) */
    float rev[MAX_VOICES], dly[MAX_VOICES];   /* each voice's sends to the reverb and delay */
    float gain;                               /* how loud it's heard (0 mutes it) */
    int on;                                   /* rendered at all (Python turns off what isn't needed) */
    int64_t awake;                            /* frames left before it sleeps: renders only while > 0 */
    int held;                                 /* notes held down (a module stays awake while any are) */
    int silent;                               /* its buffer is all zeros (asleep) */
    int slot;                                 /* the instrument slot it belongs to, or -1 (mixed on its own) */
    float buf[MAX_BLOCK * MAX_VOICES];        /* this cycle's sound, interleaved */
} Source;

static Source sources[MAX_SOURCES];

/* ------------------------------------------------------------------ queues */

enum { EV_TRIGGER = 1, EV_MIDI = 2, EV_CALL = 3, EV_TRANSPORT = 4 };
enum { T_PLAY = 1, T_STOP = 2, T_LOCATE = 3, T_RECORD = 4, T_RECORD_OFF = 5 };

typedef struct {
    uint64_t frame;                           /* when (core frames); 0 = as soon as possible */
    int32_t kind, src;
    intptr_t a, b, c;
    void *fn;                                 /* EV_CALL: fn(a, b, c) */
} Event;

#define EVENTS 4096                           /* power of two */
static Event events[EVENTS];
static atomic_uint_fast64_t ev_head, ev_tail;  /* Python writes at head, the core reads at tail */
/* the core's own list of events not due yet, and this cycle's due ones (only the audio thread uses these) */
static Event waiting[EVENTS], due[EVENTS];
static uint64_t waiting_order[EVENTS], due_order[EVENTS], next_order;
static int waiting_n;

#define MIDI_IN 1024
static struct { uint64_t frame; uint8_t b[4]; } midi_in[MIDI_IN];
static atomic_uint_fast64_t mi_head, mi_tail;  /* the core writes, Python reads */

#define MIDI_OUT 1024
static uint8_t midi_out[MIDI_OUT][4];          /* [0] = length */
static atomic_uint_fast64_t mo_head, mo_tail;  /* Python writes, the core sends */

#define DISPLAY_BYTES 1032
static uint8_t display[2][DISPLAY_BYTES];
static atomic_int display_ready = -1;          /* which buffer has a new frame to send, or -1 */
static int display_next;

/* ------------------------------------------------------------------ the rest of the state */

static void *client, *out_l, *out_r, *in_l, *in_r, *ctl_in, *ctl_out, *disp_out;
static atomic_uint_fast64_t now_frame;         /* frames played since the core started */
static atomic_uint cycles;
static jack_nframes_t rate, block;

static void (*rev_process)(void *, const float *, const float *, float *, float *, int);
static void (*dly_process)(void *, const float *, const float *, float *, float *, int);
static void *reverb, *delay;
static float rev_level = 0.0f, dly_level = 0.0f;
static float master = 1.0f, mix_gain = 0.6f;
static void (*ins_fn)(void *, float *, float *, int);   /* an instrument's insert effect (Schwung audio_fx): sh_fx_process */
static float send_l[2][MAX_BLOCK], fx_out[4][MAX_BLOCK], mix[2][MAX_BLOCK];
static float send_d[2][MAX_BLOCK];

/* a recording of what's heard, in four parts, for finding out what makes a sound (0: the instruments, dry;
   1: the tape; 2: the reverb's return; 3: the delay's return), mono, the last CAP_FRAMES frames */
#define CAP_FRAMES (30 * 44100)
#define CAP_PARTS 4
static float cap[CAP_PARTS][CAP_FRAMES], cap_now[CAP_PARTS][MAX_BLOCK];
static int64_t cap_pos;
static int capture_on;
static float ext_monitor = 0.0f;                      /* how loud the Move's audio input is heard (0: not) */
static int ext_stereo = 1;                            /* 1: left and right as they are; 0: the left on both sides */

static void flush_denormals(void) {
#if defined(__aarch64__)
    uint64_t fpcr;
    __asm__ volatile("mrs %0, fpcr" : "=r"(fpcr));
    fpcr |= (1ull << 24);
    __asm__ volatile("msr fpcr, %0" : : "r"(fpcr));
#elif defined(__SSE__)
    _mm_setcsr(_mm_getcsr() | 0x8040);
#endif
}

/* ------------------------------------------------------------------ instrument slots: their recording inputs

   Each slot (the INSTRUMENTS page) groups its machine's two sources (sequencer and hands) and makes what the
   tape can record from it, as the Python engine did: SLOT_CH channels each cycle,
     0-7  each drum on its own (DRUM 1-8)
     8-9  the kit in stereo, with the slot's own reverb and delay printed in (KIT L / KIT R)
     10   the kit in mono (KIT)
   and, if it's being heard, adds it to the mix (with its sends to the main effects). After the slots come the
   Move's own audio inputs (two channels). */

#define SLOTS 8
#define SLOT_CH 11
#define DRUM_KIT 8
#define EXT_IN (SLOTS * SLOT_CH)              /* the Move's audio input: channels EXT_IN, EXT_IN + 1 */
#define IN_CHANNELS (EXT_IN + 2)

#define PU_STAGES 5                           /* punch-in stages: TIME (fx 1-8), FILTER (9-11), CRUSH (12), GATE (13), KILL (16) */
static const int PU_FIRST[PU_STAGES] = {1, 9, 12, 13, 16}, PU_LAST[PU_STAGES] = {8, 11, 12, 13, 16};
static int pu_pick(int mask, int st) {         /* the effect of that stage in the mask (0: none) */
    for (int fx = PU_FIRST[st]; fx <= PU_LAST[st]; fx++) if (mask & (1 << (fx - 1))) return fx;
    return 0;
}
static int pu_over(int base, int top) {        /* top's effects win their groups (TIME: 1-8, FILTER: 9-11, the rest alone) */
    if (top & 0xFF) base &= ~0xFF;
    if (top & 0x700) base &= ~0x700;
    return base | top;
}

typedef struct {
    int used, src[2], voices;
    int lane[MAX_VOICES];                     /* voice -> DRUM n channel (0-7), or -1 */
    float pan[MAX_VOICES][2], rev[MAX_VOICES], dly[MAX_VOICES];
    float monitor;                            /* how loud it's heard (0: not heard) */
    void *frev, *fdly;                        /* its own effects, for the KIT inputs (NULL: none) */
    void *ins_h[4];                           /* its insert effects (NULL: none), in series, on the kit's direct sound before the tape sees
                                                 it: 0-1 its own INSERT 1 / 2, 2-3 its copy of the song's SONG INSERT 1 / 2 */
    float ins_dry[4];                         /* how much of each insert is left dry (0: all through it, the default; 1: skipped) */
    int64_t fx_tail;                          /* frames its effects keep running after the sends go to 0 */
    void *pu_h[2][PU_STAGES];                 /* its punch-in effects (fx.c's punch_process): seq / live voices, by stage */
    int pu_seq, pu_live, pu_cur;              /* masks (bit fx-1): the steps', the pads held (win their groups), playing */
    int pu_busy[2][PU_STAGES];                /* still sounding (fading out) */
    float pu_fpb;                             /* frames per beat */
    int64_t pu_age;                           /* frames since pu_cur started (PAN SWING's sway) */
} Slot;
static int (*pu_fn)(void *, float *, int, int, int, float, double);
static Slot slots[SLOTS];
static float inputs[IN_CHANNELS][MAX_BLOCK];
static float in_peak[IN_CHANNELS];            /* loudest sample since Python last asked */
static float slot_send[4][MAX_BLOCK], slot_fx[4][MAX_BLOCK];
static float ins_keep[2][MAX_BLOCK];          /* an insert's dry sound, kept to mix back in (its wet/dry amount) */

/* ------------------------------------------------------------------ the tape

   Python owns the tape's memory (numpy arrays: track t, and t + 8 for the right side of a stereo track) and
   all the bookkeeping (boxes, undo, the drawn levels). The core plays and records it, sample by sample, and
   says which stretch of which channel it recorded. */

#define TRACKS 8
#define CHANNELS 16
typedef struct { int64_t a, b, fi, fo; float g, unused; } Box;     /* frames; gain; fades in frames */
static struct { const Box *b; int n; } boxes[CHANNELS][2];
static atomic_int box_cur[CHANNELS];
static float *track[CHANNELS];
static int64_t tape_frames;
static float t_vol[TRACKS], t_pan[TRACKS], t_rev[TRACKS], t_dly[TRACKS];
static int t_audible[TRACKS], t_stereo[TRACKS], t_armed[TRACKS], t_src[TRACKS][2];
static int tape_heard = 1, playing, recording, overdub, loop_on;
static int64_t tpos, loop_a, loop_b, punch_a, punch_b;
static int64_t rec_lo[CHANNELS], rec_hi[CHANNELS];     /* what was recorded since Python last asked */
static float *undo[CHANNELS];                 /* where to keep what recording writes over (Python's memory) */
static int64_t saved_lo[CHANNELS], saved_hi[CHANNELS];  /* what's been kept so far this pass */
static atomic_flag rec_lock = ATOMIC_FLAG_INIT;

static inline float fade_curve(float u) {
    if (u <= 0.0f) return 0.0f;
    if (u >= 1.0f) return 1.0f;
    return 0.5f - 0.5f * cosf(3.14159265f * u);
}

static inline float saturate(float x) {        /* gentle tape-style limit above 0.8, as the Python engine */
    float y = fabsf(x);
    if (y <= 0.8f) return x;
    float z = 0.8f + 0.2f * tanhf((y - 0.8f) / 0.2f);
    return x < 0 ? -z : z;
}

/* the boxes' gain and fades for channel c at frames idx .. idx + m - 1, into env (1 where no box changes it) */
static void envelope(int c, int64_t idx, int m, float *env) {
    for (int i = 0; i < m; i++) env[i] = 1.0f;
    int cur = atomic_load(&box_cur[c]);
    const Box *bx = boxes[c][cur].b;
    int nb = boxes[c][cur].n;
    if (!bx) return;
    int64_t lo = idx, hi = idx + m;
    for (int k = 0; k < nb; k++) {
        const Box *r = &bx[k];
        if (r->a >= hi) break;
        if (r->b <= lo) continue;
        if (r->g == 1.0f && !r->fi && !r->fo) continue;
        int64_t f0 = r->a > lo ? r->a : lo, f1 = r->b < hi ? r->b : hi;
        for (int64_t f = f0; f < f1; f++) {
            float e = r->g;
            if (r->fi && f < r->a + r->fi) e *= fade_curve((float)(f - r->a) / (float)r->fi);
            if (r->fo && f >= r->b - r->fo) e *= fade_curve((float)(r->b - f) / (float)r->fo);
            env[f - lo] = e;
        }
    }
}

static void note_recorded(int c, int64_t a, int64_t b) {
    while (atomic_flag_test_and_set(&rec_lock)) ;
    if (rec_lo[c] < 0 || a < rec_lo[c]) rec_lo[c] = a;
    if (b > rec_hi[c]) rec_hi[c] = b;
    atomic_flag_clear(&rec_lock);
}

/* play and record frames [i0, i0 + m) of this cycle, which are tape frames p .. p + m - 1 (no loop end in between) */
static void tape_stretch(int i0, int m, int64_t p) {
    static float env0[MAX_BLOCK], env1[MAX_BLOCK];
    if (tape_heard) {
        for (int t = 0; t < TRACKS; t++) {
            if (!t_audible[t] || !track[t]) continue;
            if (recording && t_armed[t] && !overdub) continue;          /* replacing it: you hear the new */
            int st = t_stereo[t] && track[t + TRACKS];
            float vol = t_vol[t], pan = t_pan[t];
            float gl = (1.0f - pan) < 1.0f ? 1.0f - pan : 1.0f, gr = (1.0f + pan) < 1.0f ? 1.0f + pan : 1.0f;
            float rs = t_rev[t], ds = t_dly[t];
            envelope(t, p, m, env0);
            if (st) envelope(t + TRACKS, p, m, env1);
            const float *x0 = track[t] + p, *x1 = st ? track[t + TRACKS] + p : x0;
            for (int i = 0; i < m; i++) {
                float a = x0[i] * vol * env0[i];
                float b = st ? x1[i] * vol * env1[i] : a;
                float l = a * gl, r = b * gr;
                mix[0][i0 + i] += l; mix[1][i0 + i] += r;
                cap_now[1][i0 + i] += 0.5f * (l + r);
                if (rs > 0.0f) { send_l[0][i0 + i] += l * rs; send_l[1][i0 + i] += r * rs; }
                if (ds > 0.0f) { send_d[0][i0 + i] += l * ds; send_d[1][i0 + i] += r * ds; }
            }
        }
    }
    if (!recording) return;
    int64_t a = p, b = p + m;
    if (punch_b > punch_a) { if (a < punch_a) a = punch_a; if (b > punch_b) b = punch_b; }   /* punch in / out */
    if (b <= a) return;
    for (int t = 0; t < TRACKS; t++) {
        if (!t_armed[t]) continue;
        int sides = (t_stereo[t] && track[t + TRACKS]) ? 2 : 1;
        for (int k = 0; k < sides; k++) {
            int c = k ? t + TRACKS : t;
            if (!track[c]) continue;
            int ch = t_src[t][k];
            float *dst = track[c];
            float *keep = undo[c];
            if (keep) {                       /* the first time this pass writes a frame: keep what was there */
                for (int64_t f = a; f < b; f++) if (f < saved_lo[c] || f >= saved_hi[c]) keep[f] = dst[f];
                if (saved_hi[c] <= saved_lo[c]) { saved_lo[c] = a; saved_hi[c] = b; }
                else { if (a < saved_lo[c]) saved_lo[c] = a; if (b > saved_hi[c]) saved_hi[c] = b; }
            }
            for (int64_t f = a; f < b; f++) {
                int i = i0 + (int)(f - p);
                float v;
                if (ch >= 0 && ch < IN_CHANNELS) v = inputs[ch][i];
                else {                                                    /* the mix: every slot's kit, mono */
                    v = 0.0f;
                    for (int s = 0; s < SLOTS; s++) if (slots[s].used) v += inputs[s * SLOT_CH + DRUM_KIT + 2][i];
                }
                dst[f] = overdub ? saturate(dst[f] + v) : v;
            }
            note_recorded(c, a, b);
        }
    }
}

static void tape_cycle(int n) {
    if (!playing || tape_frames <= 0) return;
    int done = 0;
    while (playing && done < n) {
        int64_t limit = (loop_on && loop_b > loop_a && tpos < loop_b) ? loop_b : tape_frames;
        int64_t m = n - done;
        if (m > limit - tpos) m = limit - tpos;
        if (m <= 0) {
            if (loop_on && loop_b > loop_a && tpos >= loop_b && limit == loop_b) { tpos = loop_a; continue; }
            playing = recording = 0;                                      /* the end of the tape */
            break;
        }
        tape_stretch(done, (int)m, tpos);
        tpos += m;
        done += (int)m;
        if (loop_on && loop_b > loop_a && tpos >= loop_b && limit == loop_b) tpos = loop_a;
    }
}

static void slots_cycle(int n) {
    for (int s = 0; s < SLOTS; s++) {
        Slot *sl = &slots[s];
        float *in = inputs[s * SLOT_CH];
        for (int c = 0; c < SLOT_CH; c++) memset(inputs[s * SLOT_CH + c], 0, sizeof(float) * n);
        if (!sl->used) continue;
        (void)in;
        Source *a = sl->src[0] >= 0 ? &sources[sl->src[0]] : NULL;
        Source *b = (sl->src[1] >= 0 && sl->src[1] != sl->src[0]) ? &sources[sl->src[1]] : NULL;
        int aon = a && a->kind && a->on && !a->silent, bon = b && b->kind && b->on && !b->silent;
        /* the punch-in effect (PUNCH FX page): on each source's voices, before anything is mixed */
        int pmask = pu_over(sl->pu_seq, sl->pu_live);
        if ((pmask & (1 << 13)) && !(sl->pu_cur & (1 << 13))) sl->pu_age = 0;   /* PAN SWING starts its sway */
        sl->pu_cur = pmask;
        float swing = 0.0f;
        int throw_ = 0;
        if (pu_fn) {
            for (int st = 0; st < PU_STAGES; st++) {                 /* each stage in turn, on the voices in place */
                int f = pu_pick(pmask, st);
                if (aon && sl->pu_h[0][st] && (f || sl->pu_busy[0][st]))
                    sl->pu_busy[0][st] = pu_fn(sl->pu_h[0][st], a->buf, n, a->voices, f, sl->pu_fpb, -1.0);
                if (bon && sl->pu_h[1][st] && (f || sl->pu_busy[1][st]))
                    sl->pu_busy[1][st] = pu_fn(sl->pu_h[1][st], b->buf, n, b->voices, f, sl->pu_fpb, -1.0);
            }
            if ((pmask & (1 << 13)) && sl->pu_fpb > 0.0f)             /* PAN SWING: the whole instrument sways */
                swing = 0.9f * sinf(6.2831853f * (float)sl->pu_age / sl->pu_fpb);
            throw_ = (pmask & (1 << 14)) != 0;                        /* ECHO THROW: all of it into the delay */
        }
        sl->pu_age += n;
        int fx = sl->frev && sl->fdly && rev_process && dly_process;
        int sending = 0;
        for (int v = 0; v < sl->voices; v++) if (sl->rev[v] > 0.0f || sl->dly[v] > 0.0f) sending = 1;
        if ((sl->pu_cur | sl->pu_live | sl->pu_seq) & (1 << 14)) sending = 1;
        int run_fx = fx && (sending || sl->fx_tail > 0);
        if (run_fx) for (int k = 0; k < 4; k++) memset(slot_send[k], 0, sizeof(float) * n);
        float *kl = inputs[s * SLOT_CH + DRUM_KIT], *kr = inputs[s * SLOT_CH + DRUM_KIT + 1];
        if (aon || bon) {
            int V = sl->voices;
            for (int v = 0; v < V; v++) {
                float pl = sl->pan[v][0] * (1.0f - swing), pr = sl->pan[v][1] * (1.0f + swing);
                float rs = sl->rev[v], ds = throw_ && sl->dly[v] < 0.85f ? 0.85f : sl->dly[v], g = sl->monitor;
                int ln = sl->lane[v];
                float *lane = (ln >= 0 && ln < DRUM_KIT) ? inputs[s * SLOT_CH + ln] : NULL;
                const float *xa = aon ? a->buf + v : NULL, *xb = bon ? b->buf + v : NULL;
                int Va = aon ? a->voices : 0, Vb = bon ? b->voices : 0;
                if ((xa && v >= Va) || (xb && v >= Vb)) continue;
                for (int i = 0; i < n; i++) {
                    float x = (xa ? xa[i * Va] : 0.0f) + (xb ? xb[i * Vb] : 0.0f);
                    float l = x * pl, r = x * pr;
                    if (lane) lane[i] += x;
                    kl[i] += l; kr[i] += r;
                    if (run_fx) {
                        slot_send[0][i] += l * rs; slot_send[1][i] += r * rs;
                        slot_send[2][i] += l * ds; slot_send[3][i] += r * ds;
                    }
                    if (g > 0.0f) {                          /* heard: sends to the main effects (the direct sound: below) */
                        float hl = l * g, hr = r * g;
                        if (rs > 0.0f) { send_l[0][i] += hl * rs; send_l[1][i] += hr * rs; }
                        if (ds > 0.0f) { send_d[0][i] += hl * ds; send_d[1][i] += hr * ds; }
                    }
                }
            }
        }
        {   /* the insert effects (two, one after the other) work on the kit's direct sound; what they make is what
               the tape records (KIT inputs) and what is heard */
            void (*ifx)(void *, float *, float *, int) = ins_fn;
            int has_ins = 0;
            for (int k = 0; k < 4; k++) {
                void *ih = sl->ins_h[k];
                if (!ifx || !ih) continue;
                float dry = sl->ins_dry[k];
                if (dry >= 1.0f) continue;                 /* turned all the way down: this instrument skips it */
                has_ins = 1;
                if (dry <= 0.0f) { ifx(ih, kl, kr, n); continue; }
                memcpy(ins_keep[0], kl, sizeof(float) * n);
                memcpy(ins_keep[1], kr, sizeof(float) * n);
                ifx(ih, kl, kr, n);
                for (int i = 0; i < n; i++) {
                    kl[i] = kl[i] * (1.0f - dry) + ins_keep[0][i] * dry;
                    kr[i] = kr[i] * (1.0f - dry) + ins_keep[1][i] * dry;
                }
            }
            float g = sl->monitor;
            if ((aon || bon || has_ins) && g > 0.0f)
                for (int i = 0; i < n; i++) {
                    float hl = kl[i] * g, hr = kr[i] * g;
                    mix[0][i] += hl; mix[1][i] += hr;
                    cap_now[0][i] += 0.5f * (hl + hr);
                }
        }
        if (run_fx) {
            /* the slot's own effects, printed into its KIT inputs (so a track's sends don't get in) */
            rev_process(sl->frev, slot_send[0], slot_send[1], slot_fx[0], slot_fx[1], n);
            dly_process(sl->fdly, slot_send[2], slot_send[3], slot_fx[2], slot_fx[3], n);
            for (int i = 0; i < n; i++) {
                kl[i] += slot_fx[0][i] * rev_level + slot_fx[2][i] * dly_level;
                kr[i] += slot_fx[1][i] * rev_level + slot_fx[3][i] * dly_level;
            }
            sl->fx_tail = sending ? 10LL * (int64_t)rate : sl->fx_tail - n;
        }
        float *mono = inputs[s * SLOT_CH + DRUM_KIT + 2];
        for (int i = 0; i < n; i++) mono[i] = 0.5f * (kl[i] + kr[i]);
    }
}

static void input_peaks(int n) {
    for (int c = 0; c < IN_CHANNELS; c++) {
        float pk = in_peak[c];
        for (int i = 0; i < n; i++) { float v = fabsf(inputs[c][i]); if (v > pk) pk = v; }
        in_peak[c] = pk;
    }
}

/* ------------------------------------------------------------------ the callback */

static void render_source(Source *s, int from, int to) {
    if (to <= from || (s->awake <= 0 && s->held <= 0)) return;
    float *out = s->buf + from * s->voices;
    if (s->kind == ENGINE) s->render(out, to - from);
    else s->sh_render(s->inst, out, to - from);
}

static void apply(const Event *e) {
    Source *s = (e->src >= 0 && e->src < MAX_SOURCES) ? &sources[e->src] : NULL;
    switch (e->kind) {
    case EV_TRIGGER:
        if (s && s->kind == ENGINE) { s->awake = TAIL; s->trigger((int)e->a, (int)e->b); }
        break;
    case EV_MIDI:
        if (s && s->kind == MODULE) {
            int st = (int)e->a & 0xF0;
            if (st == 0x90 && e->c > 0) s->held++;
            else if ((st == 0x80 || st == 0x90) && s->held > 0) s->held--;
            else if (st == 0xB0 && (e->b == 123 || e->b == 120)) s->held = 0;     /* all notes off */
            s->awake = TAIL;
            s->sh_midi(s->inst, (int)e->a, (int)e->b, (int)e->c);
        }
        break;
    case EV_CALL: if (e->fn) ((void (*)(intptr_t, intptr_t, intptr_t))e->fn)(e->a, e->b, e->c); break;
    case EV_TRANSPORT:
        switch (e->a) {
        case T_PLAY: tpos = (int64_t)e->b; playing = 1; break;
        case T_STOP: playing = recording = 0; break;
        case T_LOCATE: tpos = (int64_t)e->b; break;
        case T_RECORD:
            for (int c = 0; c < CHANNELS; c++) saved_lo[c] = saved_hi[c] = 0;
            recording = 1; playing = 1;
            break;
        case T_RECORD_OFF: recording = 0; break;
        }
        break;
    }
}

static int process(jack_nframes_t n, void *arg) {
    (void)arg;
    static int fz;
    if (!fz) { flush_denormals(); fz = 1; }
    if (n > MAX_BLOCK) n = MAX_BLOCK;
    uint64_t t0 = atomic_load(&now_frame), t1 = t0 + n;

    /* the Move's controls -> Python */
    void *cin = J.port_get_buffer(ctl_in, n);
    uint32_t k = J.midi_get_event_count(cin);
    for (uint32_t i = 0; i < k; i++) {
        jack_midi_event_t ev;
        if (J.midi_event_get(&ev, cin, i) || ev.size < 1 || ev.size > 3) continue;
        uint64_t h = atomic_load(&mi_head);
        if (h - atomic_load(&mi_tail) >= MIDI_IN) break;          /* Python isn't reading: drop */
        midi_in[h % MIDI_IN].frame = t0 + ev.time;
        memset(midi_in[h % MIDI_IN].b, 0, 4);
        memcpy(midi_in[h % MIDI_IN].b, ev.buffer, ev.size);
        atomic_store(&mi_head, h + 1);
    }

    /* take everything Python has queued into the waiting list (events can arrive in any order: steps sent
       ahead, then a pad hit for right now) */
    for (;;) {
        uint64_t tail = atomic_load(&ev_tail);
        if (tail == atomic_load(&ev_head) || waiting_n >= EVENTS) break;
        waiting[waiting_n] = events[tail % EVENTS];
        waiting_order[waiting_n] = next_order++;
        waiting_n++;
        atomic_store(&ev_tail, tail + 1);
    }
    /* this cycle's events, earliest first (same frame: the order they were sent), out of the waiting list */
    int due_n = 0;
    for (int i = 0; i < waiting_n; ) {
        if (waiting[i].frame < t1) {
            Event e = waiting[i];
            uint64_t o = waiting_order[i];
            int j = due_n++;
            while (j > 0 && (due[j - 1].frame > e.frame || (due[j - 1].frame == e.frame && due_order[j - 1] > o))) {
                due[j] = due[j - 1]; due_order[j] = due_order[j - 1]; j--;
            }
            due[j] = e; due_order[j] = o;
            waiting_n--;
            waiting[i] = waiting[waiting_n];
            waiting_order[i] = waiting_order[waiting_n];
        } else i++;
    }
    /* play them, each at its exact frame: every source renders up to it first */
    int pos = 0;
    for (int i = 0; i < due_n; i++) {
        Event *e = &due[i];
        int at = e->frame <= t0 ? 0 : (int)(e->frame - t0);
        if (at > pos) {
            for (int s = 0; s < MAX_SOURCES; s++)
                if (sources[s].kind && sources[s].on) render_source(&sources[s], pos, at);
            pos = at;
        }
        apply(e);
    }
    for (int s = 0; s < MAX_SOURCES; s++)
        if (sources[s].kind && sources[s].on) render_source(&sources[s], pos, n);
    for (int s = 0; s < MAX_SOURCES; s++) {
        Source *src = &sources[s];
        if (!src->kind || !src->on) continue;
        if (src->awake <= 0 && src->held <= 0 && !src->silent) {
            memset(src->buf, 0, sizeof(float) * n * src->voices);   /* asleep: nothing to mix */
            src->silent = 1;
        }
        if (src->awake > 0 || src->held > 0) src->silent = 0;
        if (src->awake > 0) src->awake -= n;
    }

    /* mix: the slots (making their recording inputs too), sources on their own, the tape */
    memset(mix[0], 0, sizeof(float) * n);
    memset(mix[1], 0, sizeof(float) * n);
    if (capture_on) for (int p = 0; p < CAP_PARTS; p++) memset(cap_now[p], 0, sizeof(float) * n);
    memset(send_l, 0, sizeof(float) * 2 * MAX_BLOCK);
    memset(send_d, 0, sizeof(float) * 2 * MAX_BLOCK);
    slots_cycle((int)n);
    {
        const float *il = J.port_get_buffer(in_l, n), *ir = J.port_get_buffer(in_r, n);
        memcpy(inputs[EXT_IN], il, sizeof(float) * n);
        memcpy(inputs[EXT_IN + 1], ir, sizeof(float) * n);
        if (ext_monitor > 0.0f)                       /* hear the Move's input (a guitar...) while you play */
            for (jack_nframes_t i = 0; i < n; i++) {
                mix[0][i] += il[i] * ext_monitor;
                mix[1][i] += (ext_stereo ? ir[i] : il[i]) * ext_monitor;
            }
    }
    input_peaks((int)n);
    for (int s = 0; s < MAX_SOURCES; s++) {
        Source *src = &sources[s];
        if (!src->kind || !src->on || src->gain <= 0.0f || src->silent || src->slot >= 0) continue;
        int V = src->voices;
        for (int v = 0; v < V; v++) {
            float gl = src->pan[v][0] * src->gain, gr = src->pan[v][1] * src->gain;
            float rs = src->rev[v], ds = src->dly[v];
            const float *x = src->buf + v;
            for (jack_nframes_t i = 0; i < n; i++) {
                float a = x[i * V];
                float l = a * gl, r = a * gr;
                mix[0][i] += l; mix[1][i] += r;
                if (rs > 0.0f) { send_l[0][i] += l * rs; send_l[1][i] += r * rs; }
                if (ds > 0.0f) { send_d[0][i] += l * ds; send_d[1][i] += r * ds; }
            }
        }
    }
    tape_cycle((int)n);
    if (reverb && rev_process) {
        rev_process(reverb, send_l[0], send_l[1], fx_out[0], fx_out[1], (int)n);
        for (jack_nframes_t i = 0; i < n; i++) { mix[0][i] += fx_out[0][i] * rev_level; mix[1][i] += fx_out[1][i] * rev_level; }
        if (capture_on) for (jack_nframes_t i = 0; i < n; i++) cap_now[2][i] = 0.5f * (fx_out[0][i] + fx_out[1][i]) * rev_level;
    }
    if (delay && dly_process) {
        dly_process(delay, send_d[0], send_d[1], fx_out[2], fx_out[3], (int)n);
        for (jack_nframes_t i = 0; i < n; i++) { mix[0][i] += fx_out[2][i] * dly_level; mix[1][i] += fx_out[3][i] * dly_level; }
        if (capture_on) for (jack_nframes_t i = 0; i < n; i++) cap_now[3][i] = 0.5f * (fx_out[2][i] + fx_out[3][i]) * dly_level;
    }

    if (capture_on) {
        for (jack_nframes_t i = 0; i < n; i++) {
            int64_t at = (cap_pos + i) % CAP_FRAMES;
            for (int p = 0; p < CAP_PARTS; p++) cap[p][at] = cap_now[p][i];
        }
        cap_pos += n;
    }
    float *ol = J.port_get_buffer(out_l, n), *orr = J.port_get_buffer(out_r, n);
    for (jack_nframes_t i = 0; i < n; i++) {
        ol[i] = tanhf(mix[0][i] * mix_gain) * master;              /* tanh: gentle limiting, as the Pi does */
        orr[i] = tanhf(mix[1][i] * mix_gain) * master;
    }

    /* lights and the screen */
    void *cout = J.port_get_buffer(ctl_out, n);
    J.midi_clear_buffer(cout);
    for (int sent = 0; sent < 64; sent++) {
        uint64_t t = atomic_load(&mo_tail);
        if (t == atomic_load(&mo_head)) break;
        uint8_t *m = midi_out[t % MIDI_OUT];
        J.midi_event_write(cout, 0, m + 1, m[0]);
        atomic_store(&mo_tail, t + 1);
    }
    void *dout = J.port_get_buffer(disp_out, n);
    J.midi_clear_buffer(dout);
    int d = atomic_exchange(&display_ready, -1);
    if (d >= 0) J.midi_event_write(dout, 0, display[d], DISPLAY_BYTES);

    atomic_store(&now_frame, t1);
    atomic_fetch_add(&cycles, 1);
    return 0;
}

/* ------------------------------------------------------------------ Python's side */

#define GET(name, field) if (!(J.field = dlsym(lib, "jack_" name))) return -2
int core_open(const char *libjack, const char *name) {
    void *lib = dlopen(libjack, RTLD_NOW | RTLD_GLOBAL);
    if (!lib) return -1;
    GET("client_open", client_open); GET("client_close", client_close); GET("activate", activate);
    GET("deactivate", deactivate); GET("port_register", port_register); GET("port_get_buffer", port_get_buffer);
    GET("set_process_callback", set_process_callback); GET("connect", connect);
    GET("get_sample_rate", get_sample_rate); GET("get_buffer_size", get_buffer_size);
    GET("midi_get_event_count", midi_get_event_count); GET("midi_event_get", midi_event_get);
    GET("midi_clear_buffer", midi_clear_buffer); GET("midi_event_write", midi_event_write);
    J.cpu_load = dlsym(lib, "jack_cpu_load");
    int status = 0;
    client = J.client_open(name, NO_START_SERVER, &status);
    if (!client) return -3;
    rate = J.get_sample_rate(client);
    block = J.get_buffer_size(client);
    out_l = J.port_register(client, "out_L", AUDIO, IS_OUTPUT, 0);
    out_r = J.port_register(client, "out_R", AUDIO, IS_OUTPUT, 0);
    in_l = J.port_register(client, "in_L", AUDIO, IS_INPUT, 0);
    in_r = J.port_register(client, "in_R", AUDIO, IS_INPUT, 0);
    ctl_in = J.port_register(client, "controls_in", MIDI, IS_INPUT, 0);
    ctl_out = J.port_register(client, "lights_out", MIDI, IS_OUTPUT, 0);
    disp_out = J.port_register(client, "display_out", MIDI, IS_OUTPUT, 0);
    if (!out_l || !out_r || !in_l || !in_r || !ctl_in || !ctl_out || !disp_out) return -4;
    for (int s = 0; s < MAX_SOURCES; s++) sources[s].kind = 0;
    for (int c = 0; c < CHANNELS; c++) { rec_lo[c] = rec_hi[c] = -1; }
    for (int t = 0; t < TRACKS; t++) { t_vol[t] = 0.8f; t_audible[t] = 1; t_src[t][0] = t_src[t][1] = -1; }
    J.set_process_callback(client, process, NULL);
    if (J.activate(client)) return -5;
    char me[300];
    const char *pairs[][2] = {{"out_L", "system:playback_1"}, {"out_R", "system:playback_2"}};
    for (int i = 0; i < 2; i++) {
        snprintf(me, sizeof me, "%s:%s", name, pairs[i][0]);
        J.connect(client, me, pairs[i][1]);
    }
    snprintf(me, sizeof me, "%s:controls_in", name);   J.connect(client, "system:midi_capture", me);
    snprintf(me, sizeof me, "%s:lights_out", name);    J.connect(client, me, "system:midi_playback");
    snprintf(me, sizeof me, "%s:display_out", name);   J.connect(client, me, "system:display");
    snprintf(me, sizeof me, "%s:in_L", name);          J.connect(client, "system:capture_1", me);
    snprintf(me, sizeof me, "%s:in_R", name);          J.connect(client, "system:capture_2", me);
    return 0;
}

void core_close(void) {
    if (client) { J.deactivate(client); J.client_close(client); client = NULL; }
}

int core_rate(void) { return (int)rate; }
int core_block(void) { return (int)block; }
uint64_t core_now(void) { return atomic_load(&now_frame); }
unsigned core_cycles(void) { return atomic_load(&cycles); }
/* JACK's own measure of how busy the audio cycle is, 0-100 (all its clients together) */
float core_load(void) { return (client && J.cpu_load) ? J.cpu_load(client) : -1.0f; }

/* a new source (call before turning it on): returns its number, or -1 */
static int new_source(int kind, int voices) {
    if (voices < 1 || voices > MAX_VOICES) return -1;
    for (int s = 0; s < MAX_SOURCES; s++) if (!sources[s].kind) {
        Source *src = &sources[s];
        memset(src->pan, 0, sizeof src->pan);
        memset(src->rev, 0, sizeof src->rev);
        memset(src->dly, 0, sizeof src->dly);
        src->voices = voices; src->gain = 1.0f; src->on = 0;
        src->awake = 0; src->held = 0; src->silent = 1; src->slot = -1;
        memset(src->buf, 0, sizeof src->buf);
        src->kind = kind;
        return s;
    }
    return -1;
}

int core_add_engine(void *render, void *trigger, int voices) {
    int s = new_source(ENGINE, voices);
    if (s >= 0) { sources[s].render = render; sources[s].trigger = trigger; }
    return s;
}

int core_add_module(void *sh_render, void *sh_midi, void *inst) {
    int s = new_source(MODULE, 2);
    if (s >= 0) {
        sources[s].sh_render = sh_render; sources[s].sh_midi = sh_midi; sources[s].inst = inst;
        sources[s].pan[0][0] = sources[s].pan[1][1] = 1.0f;          /* stereo as it comes */
    }
    return s;
}

/* turn a source off before removing it, and wait a cycle (core_cycles) before freeing what it uses */
void core_source_on(int s, int on) { if (s >= 0 && s < MAX_SOURCES) sources[s].on = on; }
void core_remove(int s) { if (s >= 0 && s < MAX_SOURCES) { sources[s].on = 0; sources[s].kind = 0; } }
void core_set_pan(int s, int v, float l, float r) {
    if (s >= 0 && s < MAX_SOURCES && v >= 0 && v < MAX_VOICES) { sources[s].pan[v][0] = l; sources[s].pan[v][1] = r; }
}
void core_set_sends(int s, int v, float rev, float dly) {
    if (s >= 0 && s < MAX_SOURCES && v >= 0 && v < MAX_VOICES) { sources[s].rev[v] = rev; sources[s].dly[v] = dly; }
}
void core_set_gain(int s, float g) { if (s >= 0 && s < MAX_SOURCES) sources[s].gain = g; }
void core_set_master(float g) { master = g; }
void core_slot_insert(int k, int pos, void *fn, void *h) {      /* fn: sh_fx_process; the same for every slot */
    if (k < 0 || k >= SLOTS || pos < 0 || pos > 3) return;    /* 0-1: the instrument's, 2-3: the song's (a copy each) */
    if (fn) ins_fn = (void (*)(void *, float *, float *, int))fn;
    slots[k].ins_h[pos] = h;
}

void core_slot_insert_mix(int k, int pos, float wet) {        /* 0-1: how much of insert pos this slot hears (1: all) */
    if (k < 0 || k >= SLOTS || pos < 0 || pos > 3) return;
    if (wet < 0.0f) wet = 0.0f;
    if (wet > 1.0f) wet = 1.0f;
    slots[k].ins_dry[pos] = 1.0f - wet;
}

void core_set_effects(void *rp, void *r, void *dp, void *d) { rev_process = rp; reverb = r; dly_process = dp; delay = d; }
void core_set_effect_levels(float r, float d) { rev_level = r; dly_level = d; }

/* queue an event; returns 0, or -1 if the queue is full */
int core_push(uint64_t frame, int kind, int src, intptr_t a, intptr_t b, intptr_t c, void *fn) {
    uint64_t h = atomic_load(&ev_head);
    if (h - atomic_load(&ev_tail) >= EVENTS) return -1;
    Event *e = &events[h % EVENTS];
    e->frame = frame; e->kind = kind; e->src = src; e->a = a; e->b = b; e->c = c; e->fn = fn;
    atomic_store(&ev_head, h + 1);
    return 0;
}

/* how far the core has got through the events (Python keeps strings for EV_CALL alive until then) */
uint64_t core_events_done(void) { return atomic_load(&ev_tail); }

/* the Move's controls: fills up to max messages of 12 bytes (8: frame, 4: MIDI); returns how many */
int core_read_midi(uint8_t *out, int max) {
    int k = 0;
    while (k < max) {
        uint64_t t = atomic_load(&mi_tail);
        if (t == atomic_load(&mi_head)) break;
        memcpy(out + 12 * k, &midi_in[t % MIDI_IN].frame, 8);
        memcpy(out + 12 * k + 8, midi_in[t % MIDI_IN].b, 4);
        atomic_store(&mi_tail, t + 1);
        k++;
    }
    return k;
}

int core_send_midi(const uint8_t *m, int len) {
    if (len < 1 || len > 3) return -1;
    uint64_t h = atomic_load(&mo_head);
    if (h - atomic_load(&mo_tail) >= MIDI_OUT) return -1;
    midi_out[h % MIDI_OUT][0] = (uint8_t)len;
    memcpy(midi_out[h % MIDI_OUT] + 1, m, len);
    atomic_store(&mo_head, h + 1);
    return 0;
}

/* a whole screen: "MOVEDISP" + 1024 bytes */
void core_set_display(const uint8_t *frame) {
    memcpy(display[display_next], frame, DISPLAY_BYTES);
    atomic_store(&display_ready, display_next);
    display_next ^= 1;
}

/* ------------------------------------------------------------------ Python's side: slots */

/* a slot: its two sources (seq, live: the same number twice if there's only one copy) */
int core_slot(int k, int seq, int live, int voices) {
    if (k < 0 || k >= SLOTS || voices < 1 || voices > MAX_VOICES) return -1;
    Slot *sl = &slots[k];
    sl->used = 0;
    for (int s = 0; s < MAX_SOURCES; s++) if (sources[s].slot == k) sources[s].slot = -1;
    memset(sl->pan, 0, sizeof sl->pan); memset(sl->rev, 0, sizeof sl->rev); memset(sl->dly, 0, sizeof sl->dly);
    for (int v = 0; v < MAX_VOICES; v++) sl->lane[v] = -1;
    sl->voices = voices; sl->src[0] = seq; sl->src[1] = live; sl->monitor = 0.0f; sl->fx_tail = 0;
    sl->pu_seq = sl->pu_live = sl->pu_cur = 0; memset(sl->pu_busy, 0, sizeof sl->pu_busy);
    if (seq >= 0 && seq < MAX_SOURCES) sources[seq].slot = k;
    if (live >= 0 && live < MAX_SOURCES) sources[live].slot = k;
    sl->used = 1;
    return 0;
}
void core_slot_clear(int k) {
    if (k < 0 || k >= SLOTS) return;
    slots[k].used = 0;
    for (int s = 0; s < MAX_SOURCES; s++) if (sources[s].slot == k) sources[s].slot = -1;
}
void core_slot_lane(int k, int v, int lane) { if (k >= 0 && k < SLOTS && v >= 0 && v < MAX_VOICES) slots[k].lane[v] = lane; }
void core_slot_mix(int k, int v, float l, float r, float rev, float dly) {
    if (k < 0 || k >= SLOTS || v < 0 || v >= MAX_VOICES) return;
    slots[k].pan[v][0] = l; slots[k].pan[v][1] = r; slots[k].rev[v] = rev; slots[k].dly[v] = dly;
}
/* the punch-in effects: fn (fx.c's punch_process) and one of slot k's (made and kept by Python): src 0 the
   sequencer's voices, 1 the hand-played ones; stage as PU_STAGES */
void core_slot_punch(int k, void *fn, int src, int stage, void *h) {
    if (k < 0 || k >= SLOTS || src < 0 || src > 1 || stage < 0 || stage >= PU_STAGES) return;
    if (fn) pu_fn = (int (*)(void *, float *, int, int, int, float, double))fn;
    slots[k].pu_h[src][stage] = h;
}
/* the effect slot k's steps say from now (0: none); called at its frame (EV_CALL) or straight away */
void core_punch_seq(intptr_t k, intptr_t fx, intptr_t fpb) {
    if (k < 0 || k >= SLOTS) return;
    slots[k].pu_seq = (int)fx;
    if (fpb > 0) slots[k].pu_fpb = (float)fpb;
}
/* the pad held on the PUNCH FX page (0: let go); wins over the steps */
void core_punch_live(int k, int fx, float fpb) {
    if (k < 0 || k >= SLOTS) return;
    slots[k].pu_live = fx;
    if (fpb > 0.0f) slots[k].pu_fpb = fpb;
}
void core_slot_monitor(int k, float g) { if (k >= 0 && k < SLOTS) slots[k].monitor = g; }
void core_slot_effects(int k, void *rev, void *dly) { if (k >= 0 && k < SLOTS) { slots[k].frev = rev; slots[k].fdly = dly; } }

/* the loudest sample on each input channel since the last call (IN_CHANNELS of them), then starts again */
int core_input_peaks(float *out) {
    for (int c = 0; c < IN_CHANNELS; c++) { out[c] = in_peak[c]; in_peak[c] = 0.0f; }
    return IN_CHANNELS;
}
int core_in_channels(void) { return IN_CHANNELS; }

/* ------------------------------------------------------------------ Python's side: the tape */

void core_tape_frames(int64_t frames) { tape_frames = frames; }
void core_tape_channel(int c, float *data) { if (c >= 0 && c < CHANNELS) track[c] = data; }
void core_tape_track(int t, float vol, float pan, float rev, float dly, int audible, int stereo) {
    if (t < 0 || t >= TRACKS) return;
    t_vol[t] = vol; t_pan[t] = pan; t_rev[t] = rev; t_dly[t] = dly; t_audible[t] = audible; t_stereo[t] = stereo;
}
/* armed: records from input channel src0 (and src1 for its right side); -1 = the mix */
void core_tape_arm(int t, int armed, int src0, int src1) {
    if (t < 0 || t >= TRACKS) return;
    t_src[t][0] = src0; t_src[t][1] = src1; t_armed[t] = armed;
}
/* a channel's boxes: n of them, sorted (Python keeps the array alive until it replaces it twice more) */
void core_tape_boxes(int c, const Box *b, int n) {
    if (c < 0 || c >= CHANNELS) return;
    int next = atomic_load(&box_cur[c]) ^ 1;
    boxes[c][next].b = b; boxes[c][next].n = n;
    atomic_store(&box_cur[c], next);
}
void core_tape_heard(int on) { tape_heard = on; }
/* where channel c keeps what recording writes over (as long as the tape; NULL: don't keep it) */
void core_tape_undo(int c, float *buf) { if (c >= 0 && c < CHANNELS) undo[c] = buf; }
void core_tape_loop(int on, int64_t a, int64_t b) { loop_a = a; loop_b = b; loop_on = on; }
void core_tape_punch(int64_t a, int64_t b) { punch_a = a; punch_b = b; }
void core_tape_overdub(int on) { overdub = on; }
int64_t core_tape_pos(void) { return tpos; }
int core_tape_state(void) { return (playing ? 1 : 0) | (recording ? 2 : 0); }
/* what channel c recorded since the last call: 1 and [*a, *b), or 0 */
int core_tape_recorded(int c, int64_t *a, int64_t *b) {
    if (c < 0 || c >= CHANNELS) return 0;
    while (atomic_flag_test_and_set(&rec_lock)) ;
    int got = rec_lo[c] >= 0;
    if (got) { *a = rec_lo[c]; *b = rec_hi[c]; rec_lo[c] = -1; rec_hi[c] = -1; }
    atomic_flag_clear(&rec_lock);
    return got;
}

/* ------------------------------------------------------------------ Python's side: listening in */
void core_ext_monitor(float g, int stereo) { ext_monitor = g; ext_stereo = stereo; }
void core_capture(int on) { if (on) { cap_pos = 0; memset(cap, 0, sizeof cap); } capture_on = on; }
/* the last n frames of part p (oldest first) into out; returns how many there were */
int core_capture_get(int p, float *out, int n) {
    if (p < 0 || p >= CAP_PARTS) return 0;
    int64_t have = cap_pos < CAP_FRAMES ? cap_pos : CAP_FRAMES;
    if (n > have) n = (int)have;
    for (int i = 0; i < n; i++) out[i] = cap[p][(cap_pos - n + i) % CAP_FRAMES];
    return n;
}
