/*
 * Console send effects: a reverb and a tape-style delay.
 *
 * The reverb is a port of the one in Mutable Instruments Elements (and Rings):
 * elements/dsp/fx/reverb.h and fx_engine.h, Copyright 2014 Emilie Gillet,
 * released under the MIT licence (see LICENSE-mutable.txt next to this file).
 * Same topology, coefficients and modulation. Changes: plain C, float storage
 * (the original packs samples into 16 bits; this keeps its clipping), and the
 * delay lengths are scaled from the module's 32 kHz to the tape's sample rate
 * so the room sounds the same size, and a ROOM setting shrinks every line (down
 * to an eighth), so it goes from Elements' big hall down to a small room
 * (Elements itself can only change how long the tail is, never the size).
 *
 * The delay is new: a stereo tape delay whose time glides (with a little
 * pitch bend, like tape) when you change it, with soft saturation and a
 * low-pass filter in the feedback so each repeat gets darker.
 *
 * Built by setup.sh (or by the app on first run):
 *   gcc -O2 -shared -fPIC -o libconsolefx.so fx.c -lm
 */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#if defined(__aarch64__)
#include <stdint.h>
#elif defined(__SSE__)
#include <xmmintrin.h>
#endif

/* Round tiny numbers to zero on the calling thread. As a reverb tail fades the numbers go "denormal" and the
   processor handles them many times slower (the effects run on silence all the time). Call once from the
   audio thread; it then covers every C library that thread calls. */
void console_flush_denormals(void) {
#if defined(__aarch64__)
    uint64_t fpcr;
    __asm__ volatile("mrs %0, fpcr" : "=r"(fpcr));
    fpcr |= (1ull << 24);                       /* FZ */
    __asm__ volatile("msr fpcr, %0" : : "r"(fpcr));
#elif defined(__SSE__)
    _mm_setcsr(_mm_getcsr() | 0x8040);          /* FTZ and DAZ */
#endif
}

/* ------------------------------------------------------------------ reverb */

#define RV_SIZE 32768                      /* power of two, like the original */
#define RV_MASK (RV_SIZE - 1)
#define RV_LINES 10

static const int RV_LENGTHS[RV_LINES] = {  /* at 32 kHz, from Elements */
    150, 214, 319, 527, 2182, 2690, 4501, 2525, 2197, 6312
};
enum { AP1, AP2, AP3, AP4, DAP1A, DAP1B, DEL1, DAP2A, DAP2B, DEL2 };

typedef struct {
    float buf[RV_SIZE];
    int base[RV_LINES], len[RV_LINES];
    int write_ptr;
    float scale;                           /* sample rate / 32000 */
    float room;                            /* 0.125..1: how much of each line is used (the room's size) */
    /* the two slow LFOs: cosine, 0..1, stepped every 32 samples as in the original */
    float lfo_phase[2], lfo_inc[2], lfo_value[2];
    float amount, input_gain, reverb_time, diffusion, lp;
    float lp_decay_1, lp_decay_2;
    float width;                           /* 0 (the two sides the same: mono) .. 1 (the reverb's own stereo) */
} Reverb;

typedef struct {                           /* fx_engine.h's Context */
    Reverb *r;
    float acc, prev;
} Ctx;

static inline float clip1(float x) {      /* what packing into 16 bits does */
    return x > 0.99997f ? 0.99997f : (x < -1.0f ? -1.0f : x);
}

static inline float rv_at(Reverb *r, int line, int offset) {
    if (offset == -1) offset = r->len[line] - 1;             /* TAIL */
    return r->buf[(r->write_ptr + r->base[line] + offset) & RV_MASK];
}

static inline void c_read(Ctx *c, int line, int offset, float scale) {
    float v = rv_at(c->r, line, offset);
    c->prev = v;
    c->acc += v * scale;
}

static inline void c_write(Ctx *c, int line, int offset, float scale) {
    Reverb *r = c->r;
    if (offset == -1) offset = r->len[line] - 1;
    r->buf[(r->write_ptr + r->base[line] + offset) & RV_MASK] = clip1(c->acc);
    c->acc *= scale;
}

static inline void c_write_allpass(Ctx *c, int line, float scale) {
    c_write(c, line, 0, scale);
    c->acc += c->prev;
}

static inline void c_lp(Ctx *c, float *state, float coef) {
    *state += coef * (c->acc - *state);
    c->acc = *state;
}

static inline void c_interpolate(Ctx *c, int line, float offset, int lfo, float amplitude, float scale) {
    Reverb *r = c->r;
    offset += amplitude * r->lfo_value[lfo];
    int i = (int)offset;
    float f = offset - (float)i;
    float a = r->buf[(r->write_ptr + i + r->base[line]) & RV_MASK];
    float b = r->buf[(r->write_ptr + i + r->base[line] + 1) & RV_MASK];
    float x = a + (b - a) * f;
    c->prev = x;
    c->acc += x * scale;
}

void rev_clear(Reverb *r) {
    memset(r->buf, 0, sizeof(r->buf));
    r->lp_decay_1 = r->lp_decay_2 = 0.0f;
}

Reverb *rev_new(float sample_rate) {
    Reverb *r = calloc(1, sizeof(Reverb));
    if (!r) return NULL;
    r->scale = sample_rate / 32000.0f;
    int base = 0;
    for (int i = 0; i < RV_LINES; i++) {
        r->len[i] = (int)(RV_LENGTHS[i] * r->scale + 0.5f);
        r->base[i] = base;
        base += r->len[i] + 1;
    }
    /* SetLFOFrequency(LFO_1, 0.5 / 32000) and (LFO_2, 0.3 / 32000): 0.5 Hz and 0.3 Hz */
    r->lfo_inc[0] = 2.0f * (float)M_PI * 0.5f / sample_rate * 32.0f;
    r->lfo_inc[1] = 2.0f * (float)M_PI * 0.3f / sample_rate * 32.0f;
    r->lfo_value[0] = r->lfo_value[1] = 0.5f;
    r->amount = 1.0f;                      /* wet only: the app mixes it in */
    r->input_gain = 0.2f;
    r->reverb_time = 0.5f;
    r->diffusion = 0.625f;
    r->lp = 0.7f;
    r->room = 1.0f;
    r->width = 1.0f;
    return r;
}

/* The room's size: every line (and the modulation) shrinks together. Lines keep their place in the
 * buffer, so changing it only shortens how far back each one reads. */
void rev_room(Reverb *r, float room) {
    if (room < 0.125f) room = 0.125f;
    if (room > 1.0f) room = 1.0f;
    r->room = room;
    for (int i = 0; i < RV_LINES; i++) {
        int n = (int)(RV_LENGTHS[i] * r->scale * room + 0.5f);
        r->len[i] = n < 4 ? 4 : n;
    }
}

void rev_free(Reverb *r) { free(r); }

/* The stereo width of the wet output: 1 as it is, 0 mono. */
void rev_width(Reverb *r, float width) {
    r->width = width < 0.0f ? 0.0f : (width > 1.0f ? 1.0f : width);
}

void rev_params(Reverb *r, float reverb_time, float lp, float diffusion, float input_gain) {
    r->reverb_time = reverb_time;
    r->lp = lp;
    r->diffusion = diffusion;
    r->input_gain = input_gain;
}

/* Wet output only. in and out may not overlap. */
void rev_process(Reverb *r, const float *in_l, const float *in_r, float *out_l, float *out_r, int n) {
    const float kap = r->diffusion, klp = r->lp, krt = r->reverb_time, gain = r->input_gain;
    const float s = r->scale * r->room, width = r->width;
    float lp_1 = r->lp_decay_1, lp_2 = r->lp_decay_2;
    Ctx c;
    c.r = r;
    for (int k = 0; k < n; k++) {
        float wet, apout;
        /* engine_.Start(&c) */
        if (--r->write_ptr < 0) r->write_ptr += RV_SIZE;
        c.acc = 0.0f;
        c.prev = 0.0f;
        if ((r->write_ptr & 31) == 0) {
            for (int i = 0; i < 2; i++) {
                r->lfo_phase[i] += r->lfo_inc[i];
                if (r->lfo_phase[i] > 2.0f * (float)M_PI) r->lfo_phase[i] -= 2.0f * (float)M_PI;
                r->lfo_value[i] = 0.5f + 0.5f * cosf(r->lfo_phase[i]);
            }
        }

        /* Smear AP1 inside the loop. */
        c_interpolate(&c, AP1, 10.0f * s, 0, 80.0f * s, 1.0f);
        c_write(&c, AP1, (int)(100.0f * s), 0.0f);

        c.acc += (in_l[k] + in_r[k]) * gain;

        /* Diffuse through 4 allpasses. */
        c_read(&c, AP1, -1, kap); c_write_allpass(&c, AP1, -kap);
        c_read(&c, AP2, -1, kap); c_write_allpass(&c, AP2, -kap);
        c_read(&c, AP3, -1, kap); c_write_allpass(&c, AP3, -kap);
        c_read(&c, AP4, -1, kap); c_write_allpass(&c, AP4, -kap);
        apout = c.acc;

        /* Main reverb loop. */
        c.acc = apout;
        c_interpolate(&c, DEL2, 6211.0f * s, 1, 100.0f * s, krt);
        c_lp(&c, &lp_1, klp);
        c_read(&c, DAP1A, -1, -kap); c_write_allpass(&c, DAP1A, kap);
        c_read(&c, DAP1B, -1, kap); c_write_allpass(&c, DAP1B, -kap);
        c_write(&c, DEL1, 0, 2.0f);
        wet = c.acc;
        c.acc = 0.0f;
        out_l[k] = wet;

        c.acc = apout;
        c_read(&c, DEL1, -1, krt);
        c_lp(&c, &lp_2, klp);
        c_read(&c, DAP2A, -1, kap); c_write_allpass(&c, DAP2A, -kap);
        c_read(&c, DAP2B, -1, -kap); c_write_allpass(&c, DAP2B, kap);
        c_write(&c, DEL2, 0, 2.0f);
        wet = c.acc;
        c.acc = 0.0f;
        out_r[k] = wet;
        if (width < 1.0f) {                                   /* narrower: the sides come towards the middle */
            float mid = 0.5f * (out_l[k] + out_r[k]), side = 0.5f * (out_l[k] - out_r[k]) * width;
            out_l[k] = mid + side;
            out_r[k] = mid - side;
        }
    }
    r->lp_decay_1 = lp_1;
    r->lp_decay_2 = lp_2;
}

/* ------------------------------------------------------------------ tape delay */

typedef struct {
    float *buf[2];
    int size, mask, w;
    float sample_rate;
    float time, target;                    /* in samples; time glides towards target */
    float glide;
    float feedback, tone;
    float lp[2], hp[2];
    float hp_coef;
} Delay;

Delay *dly_new(float sample_rate, float max_seconds) {
    Delay *d = calloc(1, sizeof(Delay));
    if (!d) return NULL;
    int size = 1;
    while (size < (int)(sample_rate * max_seconds) + 4) size <<= 1;
    d->size = size;
    d->mask = size - 1;
    for (int i = 0; i < 2; i++) {
        d->buf[i] = calloc(size, sizeof(float));
        if (!d->buf[i]) { free(d->buf[0]); free(d); return NULL; }
    }
    d->sample_rate = sample_rate;
    d->time = d->target = sample_rate * 0.375f;
    d->glide = 1.0f / (0.1f * sample_rate);        /* glides to a new time over about 0.1 s */
    d->feedback = 0.4f;
    d->tone = 0.6f;
    d->hp_coef = 2.0f * (float)M_PI * 60.0f / sample_rate;   /* keeps the low end from piling up */
    return d;
}

void dly_free(Delay *d) {
    if (!d) return;
    free(d->buf[0]);
    free(d->buf[1]);
    free(d);
}

void dly_clear(Delay *d) {
    memset(d->buf[0], 0, d->size * sizeof(float));
    memset(d->buf[1], 0, d->size * sizeof(float));
    d->lp[0] = d->lp[1] = d->hp[0] = d->hp[1] = 0.0f;
}

void dly_params(Delay *d, float time_samples, float feedback, float tone) {
    float max = (float)(d->size - 4);
    d->target = time_samples < 1.0f ? 1.0f : (time_samples > max ? max : time_samples);
    d->feedback = feedback;
    d->tone = tone;
}

static inline float soft(float x) {       /* gentle tape-like saturation */
    return x / (1.0f + fabsf(x) * 0.25f);
}

/* Wet output only. */
void dly_process(Delay *d, const float *in_l, const float *in_r, float *out_l, float *out_r, int n) {
    /* tone 0..1 -> low-pass in the feedback from about 1.2 kHz to 12 kHz */
    float cutoff = 1200.0f * powf(10.0f, d->tone);
    float lpc = 1.0f - expf(-2.0f * (float)M_PI * cutoff / d->sample_rate);
    const float *in[2] = {in_l, in_r};
    float *out[2] = {out_l, out_r};
    for (int k = 0; k < n; k++) {
        d->time += (d->target - d->time) * d->glide;
        float pos = (float)d->w - d->time;
        while (pos < 0.0f) pos += (float)d->size;
        int i = (int)pos;
        float f = pos - (float)i;
        for (int c = 0; c < 2; c++) {
            float a = d->buf[c][i & d->mask];
            float b = d->buf[c][(i + 1) & d->mask];
            float y = a + (b - a) * f;
            out[c][k] = y;
            d->lp[c] += lpc * (y - d->lp[c]);
            float x = d->lp[c];
            d->hp[c] += d->hp_coef * (x - d->hp[c]);
            x -= d->hp[c];
            d->buf[c][d->w] = soft(in[c][k] + x * d->feedback);
        }
        d->w = (d->w + 1) & d->mask;
    }
}

/* ------------------------------------------------------------------ punch-in effects
 *
 * One instrument's punch-in effect (OP-XY style), on its voices before they're panned and sent: buf is
 * (frames, chans) float32, row after row, changed in place. fx 0 is none; the others as PUNCH_NAMES in
 * punch.py. A short history of the input is always kept (REVERSE plays the beat just gone). Changing the
 * effect fades over a few ms so nothing clicks. */

#define PU_MAXCH 64
#define PU_SECONDS 1.6f                    /* the history: enough for a beat down to about 80 BPM */

typedef struct {
    float rate;
    int chans, len, w;                     /* history: len frames x chans, w the next frame written */
    float *hist;
    int cur;                               /* the effect running (it fades out after fx goes to 0) */
    long age;                              /* frames since it started */
    int start;                             /* where in the history it started */
    double pos;                            /* TAPE STOP / HALF SPEED: how far into the history they've read */
    float mix, gate;
    int crush_n;
    float held[PU_MAXCH];
    float z1[PU_MAXCH], z2[PU_MAXCH];      /* the filters' states */
    float b0, b1, b2, a1, a2;
} Punch;

Punch *punch_new(float rate) {
    Punch *p = (Punch *)calloc(1, sizeof(Punch));
    if (p)
        p->rate = rate;
    return p;
}

/* make the history for this many channels now (not in the audio thread) */
void punch_prepare(Punch *p, int chans) {
    if (!p || chans < 1 || chans > PU_MAXCH || (p->hist && p->chans == chans))
        return;
    float *old = p->hist;
    p->len = (int)(p->rate * PU_SECONDS);
    p->hist = (float *)calloc((size_t)p->len * chans, sizeof(float));
    p->chans = p->hist ? chans : 0;
    p->w = 0;
    p->cur = 0;
    p->mix = 0.0f;
    free(old);
}

void punch_free(Punch *p) {
    if (p) {
        free(p->hist);
        free(p);
    }
}

static void pu_biquad(Punch *p, int kind, float f, float q) {   /* kind 0 low pass, 1 high pass, 2 band pass */
    float nyq = p->rate * 0.45f;
    if (f > nyq) f = nyq;
    if (f < 10.0f) f = 10.0f;
    float w0 = 2.0f * 3.14159265f * f / p->rate, cw = cosf(w0), al = sinf(w0) / (2.0f * q);
    float a0 = 1.0f + al;
    if (kind == 0) {
        p->b0 = (1.0f - cw) * 0.5f / a0; p->b1 = (1.0f - cw) / a0; p->b2 = p->b0;
    } else if (kind == 1) {
        p->b0 = (1.0f + cw) * 0.5f / a0; p->b1 = -(1.0f + cw) / a0; p->b2 = p->b0;
    } else {
        p->b0 = al / a0; p->b1 = 0.0f; p->b2 = -al / a0;
    }
    p->a1 = -2.0f * cw / a0;
    p->a2 = (1.0f - al) / a0;
}

static inline float pu_hist(Punch *p, long frame, int c) {   /* frame: any whole number, wrapped */
    long i = frame % p->len;
    if (i < 0) i += p->len;
    return p->hist[i * p->chans + c];
}

static inline float pu_hist_f(Punch *p, double frame, int c) {
    long i = (long)floor(frame);
    float t = (float)(frame - i);
    return pu_hist(p, i, c) * (1.0f - t) + pu_hist(p, i + 1, c) * t;
}

static const float PU_REPEAT[] = {0, 1.0f, 0.5f, 0.25f, 0.125f, 1.0f / 3.0f};   /* fx 1-5: beats per slice */

/* fpb: frames per beat. beat: where the block starts in beats (for GATE), or < 0: count from the start.
   Returns 1 while an effect is still sounding (running or fading), else 0. */
int punch_process(Punch *p, float *buf, int frames, int chans, int fx, float fpb, double beat) {
    if (chans < 1 || chans > PU_MAXCH || frames <= 0)
        return 0;
    /* only the TIME effects (1-8) need the history: the other stages never make one */
    int need = (fx >= 1 && fx <= 8) || (p->cur >= 1 && p->cur <= 8);
    if (p->hist && chans != p->chans) {
        free(p->hist);
        p->hist = NULL;
        p->cur = 0;
        p->mix = 0.0f;
    }
    if (!p->hist && need) {
        p->len = (int)(p->rate * PU_SECONDS);
        p->hist = (float *)calloc((size_t)p->len * chans, sizeof(float));
        p->w = 0;
        if (!p->hist)
            return 0;
    }
    p->chans = chans;
    int keep = p->hist != NULL;
    if (fpb < 16.0f) fpb = 16.0f;
    if (p->len > 0 && fpb > p->len * 0.45f) fpb = p->len * 0.45f;   /* (a very slow tempo: shorter, so it fits the history) */
    if (fx != 0 && fx != p->cur) {                           /* a new effect: start it */
        p->cur = fx;
        p->age = 0;
        p->start = p->w;
        p->pos = 0.0;
        p->mix = 0.0f;
        p->gate = 1.0f;
        p->crush_n = 0;
        memset(p->z1, 0, sizeof p->z1);
        memset(p->z2, 0, sizeof p->z2);
    }
    float target = fx ? 1.0f : 0.0f;
    float ramp = 1.0f / (0.004f * p->rate);
    if (p->cur == 0 && p->mix <= 0.0f) {                     /* nothing running: just keep the history */
        if (!keep)
            return 0;
        for (int i = 0; i < frames; i++) {
            memcpy(p->hist + (size_t)p->w * chans, buf + (size_t)i * chans, sizeof(float) * chans);
            if (++p->w >= p->len) p->w = 0;
        }
        return 0;
    }
    int cur = p->cur;
    float wet[PU_MAXCH];
    for (int i = 0; i < frames; i++) {
        float *x = buf + (size_t)i * chans;
        if (keep)
            memcpy(p->hist + (size_t)p->w * chans, x, sizeof(float) * chans);
        long age = p->age;
        if ((age & 15) == 0) {                               /* the filters move every 16 frames */
            float t = age / fpb;
            if (cur == 9)
                pu_biquad(p, 0, 18000.0f * powf(250.0f / 18000.0f, t > 1.0f ? 1.0f : t), 1.0f);
            else if (cur == 10)
                pu_biquad(p, 1, 30.0f * powf(3000.0f / 30.0f, t > 1.0f ? 1.0f : t), 1.0f);
            else if (cur == 11)
                pu_biquad(p, 2, 350.0f * powf(2.0f, 2.6f * (0.5f - 0.5f * cosf(6.2831853f * t))), 5.0f);
        }
        if (cur >= 1 && cur <= 5) {                          /* REPEAT: the first slice plays, then loops */
            long L = (long)(PU_REPEAT[cur] * fpb);
            if (L < 32) L = 32;
            if (age < L) {
                for (int c = 0; c < chans; c++) wet[c] = x[c];
            } else {
                long k = age % L;
                float g = 1.0f;
                if (k < 48) g = k / 48.0f;
                else if (L - k < 48) g = (L - k) / 48.0f;
                for (int c = 0; c < chans; c++) wet[c] = pu_hist(p, p->start + k, c) * g;
            }
        } else if (cur == 6) {                               /* REVERSE: the beat just gone, backwards, round */
            long L = (long)fpb;
            long k = age % L;
            float g = 1.0f;
            if (k < 48) g = k / 48.0f;
            else if (L - k < 48) g = (L - k) / 48.0f;
            for (int c = 0; c < chans; c++) wet[c] = pu_hist(p, p->start - 1 - k, c) * g;
        } else if (cur == 7) {                               /* TAPE STOP: slows to a halt over a beat */
            float r = 1.0f - age / fpb;
            if (r < 0.0f) r = 0.0f;
            float g = r < 0.05f ? r / 0.05f : 1.0f;
            for (int c = 0; c < chans; c++) wet[c] = pu_hist_f(p, p->start + p->pos, c) * g;
            p->pos += r;
        } else if (cur == 8) {                               /* HALF SPEED: an octave down, catching up each half beat */
            double lag = age - p->pos;
            if (lag > fpb * 0.5) p->pos += fpb * 0.5;
            double ph = fmod(p->pos, fpb * 0.25);
            float g = ph < 48 ? (float)(ph / 48.0) : 1.0f;
            for (int c = 0; c < chans; c++) wet[c] = pu_hist_f(p, p->start + p->pos, c) * g;
            p->pos += 0.5;
        } else if (cur >= 9 && cur <= 11) {                  /* LOW PASS / HIGH PASS sweeps, RESO PEAK (a wah) */
            for (int c = 0; c < chans; c++) {
                float in = x[c];
                float y = p->b0 * in + p->z1[c];
                p->z1[c] = p->b1 * in - p->a1 * y + p->z2[c];
                p->z2[c] = p->b2 * in - p->a2 * y;
                wet[c] = cur == 11 ? 0.35f * in + 2.2f * y : y;
            }
        } else if (cur == 12) {                              /* BITCRUSH: fewer samples, fewer steps */
            if (p->crush_n == 0)
                for (int c = 0; c < chans; c++) p->held[c] = roundf(x[c] * 12.0f) / 12.0f;
            if (++p->crush_n >= 6) p->crush_n = 0;
            for (int c = 0; c < chans; c++) wet[c] = p->held[c];
        } else if (cur == 13) {                              /* GATE 1/16: on for the first half of each 16th */
            double b = beat >= 0 ? beat + i / fpb : age / fpb;
            double ph = (b * 4.0) - floor(b * 4.0);
            float want = ph < 0.5 ? 1.0f : 0.0f;
            p->gate += (want - p->gate) * 0.02f;
            for (int c = 0; c < chans; c++) wet[c] = x[c] * p->gate;
        } else if (cur == 16) {                              /* KILL */
            for (int c = 0; c < chans; c++) wet[c] = 0.0f;
        } else {                                             /* (PAN SWING, ECHO THROW: done outside) */
            for (int c = 0; c < chans; c++) wet[c] = x[c];
        }
        float m = p->mix;
        for (int c = 0; c < chans; c++) x[c] += m * (wet[c] - x[c]);
        if (m < target) { m += ramp; if (m > 1.0f) m = 1.0f; }
        else if (m > target) { m -= ramp; if (m < 0.0f) m = 0.0f; }
        p->mix = m;
        p->age++;
        if (keep && ++p->w >= p->len) p->w = 0;
    }
    if (p->mix <= 0.0f && fx == 0)
        p->cur = 0;
    return p->cur != 0;
}
