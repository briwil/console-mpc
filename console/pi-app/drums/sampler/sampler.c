/* The SAMPLER's sound engine: 16 sample players, one per drum, each its own output channel (Console's sound core
 * calls sw_render, like the other drum machines' libraries in drums/schwung/glue_common.h). Samples are loaded by
 * Python (sw_load); settings are sw_set("<name><drum>", value) with the names below.
 *
 * Each drum has up to five samples (sw_load(16 * w + drum, ...), w 0-4). RANDOM off (random<drum> 0): samples 1
 * and 2 play together from the same hit with the same pitch, start and decay, and BLEND (0-127) between them: 0
 * only the first, 64 both at full volume, 127 only the second (read as the sound plays, so an LFO on it morphs a
 * ringing sample); 3-5 are silent. RANDOM on: each hit plays one of the loaded samples 1-5, picked at random,
 * and BLEND is ignored. solo<drum> n (1-5, not saved): the sample browser's preview plays only sample n. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define VOICES 16
#define SAMPLES 5
typedef struct { float *x; int n; int on; double pos; } player_t;      /* one sample of a drum, playing */
typedef struct { player_t p[SAMPLES]; double rate; float gain; int age, fade, pick; float mixed[SAMPLES]; } voice_t;
                                                         /* mixed: last block's BLEND gains; pick: RANDOM's sample */
static voice_t V[VOICES];
static int level[VOICES], pitch[VOICES], start[VOICES], decay[VOICES], blend[VOICES], rnd[VOICES], solo[VOICES];
static float RATE = 44100.f;
static int inited = 0;

static int parse(const char *key, char *name, int cap)
{
    int i = 0;
    while (key[i] && !(key[i] >= '0' && key[i] <= '9') && i < cap - 1) { name[i] = key[i]; i++; }
    name[i] = 0;
    return key[i] ? atoi(key + i) : -1;
}

int sw_init(float sr)
{
    if (!inited) {
        inited = 1;
        RATE = sr;
        memset(V, 0, sizeof V);
        for (int i = 0; i < VOICES; i++) { level[i] = 100; pitch[i] = 64; start[i] = 0; decay[i] = 127; blend[i] = 0; }
    }
    return VOICES;
}

int sw_voices(void) { return VOICES; }

void sw_set(const char *key, int value)
{
    char name[16];
    int v = parse(key, name, sizeof name) - 1;       /* "level3" is the third drum */
    if (v < 0 || v >= VOICES) return;
    if (value < 0) value = 0;
    if (value > 127) value = 127;
    if (!strcmp(name, "level")) level[v] = value;
    else if (!strcmp(name, "pitch")) pitch[v] = value;
    else if (!strcmp(name, "start")) start[v] = value;
    else if (!strcmp(name, "decay")) decay[v] = value;
    else if (!strcmp(name, "blend")) blend[v] = value;
    else if (!strcmp(name, "random")) rnd[v] = value ? 1 : 0;
    else if (!strcmp(name, "solo")) solo[v] = value <= SAMPLES ? value : 0;
}

int sw_get(const char *key)
{
    char name[16];
    int v = parse(key, name, sizeof name) - 1;
    if (v < 0 || v >= VOICES) return -1;
    if (!strcmp(name, "level")) return level[v];
    if (!strcmp(name, "pitch")) return pitch[v];
    if (!strcmp(name, "start")) return start[v];
    if (!strcmp(name, "decay")) return decay[v];
    if (!strcmp(name, "blend")) return blend[v];
    if (!strcmp(name, "random")) return rnd[v];
    return -1;
}

/* the sample for a drum (mono floats at the engine's rate): voice 0-15 its first sample, 16-31 its second ...
   64-79 its fifth; n = 0 empties it */
void sw_load(int voice, const float *data, int n)
{
    if (voice < 0 || voice >= VOICES * SAMPLES) return;
    int which = voice / VOICES;
    voice %= VOICES;
    player_t *p = &V[voice].p[which];
    float *old = p->x;
    float *copy = 0;
    if (data && n > 1) {
        copy = (float *)malloc(sizeof(float) * n);
        if (copy) memcpy(copy, data, sizeof(float) * n);
    }
    p->on = 0;
    p->x = copy;
    p->n = copy ? n : 0;
    if (old) free(old);
}

/* BLEND's gain for each sample of drum v: only samples 1 and 2 (3-5 are RANDOM's), as before: the first full up
   to the middle then fading out, the second fading in up to the middle (if just one of them is loaded: full) */
static void gains(int v, float *g)
{
    int b = blend[v];
    for (int w = 0; w < SAMPLES; w++) g[w] = 0.f;
    int a = V[v].p[0].x && V[v].p[0].n >= 2, c = V[v].p[1].x && V[v].p[1].n >= 2;
    g[0] = !c ? 1.f : b <= 64 ? 1.f : (127 - b) / 63.f;       /* (only one of the two loaded: it plays full) */
    g[1] = !a ? 1.f : b >= 64 ? 1.f : b / 64.f;
}

void sw_trigger(int voice, int velocity)
{
    if (voice < 0 || voice >= VOICES || velocity <= 0) return;
    voice_t *p = &V[voice];
    int loaded[SAMPLES], n = 0;
    for (int w = 0; w < (rnd[voice] ? SAMPLES : 2); w++)      /* (RANDOM off: samples 3-5 are silent) */
        if (p->p[w].x && p->p[w].n >= 2) loaded[n++] = w;
    int sl = solo[voice] && p->p[solo[voice] - 1].x && p->p[solo[voice] - 1].n >= 2;
    if (!n && !sl) return;
    p->pick = sl ? solo[voice] - 1                        /* the browser's preview: only that sample */
                 : rnd[voice] ? loaded[rand() % n] : -1;
    for (int w = 0; w < SAMPLES; w++) {
        player_t *q = &p->p[w];
        q->on = q->x && q->n >= 2 && (p->pick < 0 ? w < 2 : p->pick == w);
        if (q->on) q->pos = (double)q->n * start[voice] / 127.0 * 0.95;
    }
    if (velocity > 127) velocity = 127;
    p->rate = pow(2.0, ((pitch[voice] - 64) / 2.0) / 12.0);
    p->gain = (level[voice] / 127.0f) * (velocity / 127.0f);
    p->age = 0;
    if (p->pick >= 0) {
        for (int w = 0; w < SAMPLES; w++) p->mixed[w] = w == p->pick ? 1.f : 0.f;
    } else gains(voice, p->mixed);                                  /* (no glide in from an old BLEND) */
    {
        double d = decay[voice] / 127.0;
        p->fade = decay[voice] >= 127 ? 0 : (int)(RATE * (0.03 + d * d * 2.5));
    }
}

/* out: frames x VOICES floats, interleaved (a drum a channel) */
void sw_render(float *out, int frames)
{
    memset(out, 0, sizeof(float) * frames * VOICES);
    for (int v = 0; v < VOICES; v++) {
        voice_t *p = &V[v];
        int playing = 0;
        for (int w = 0; w < SAMPLES; w++) playing |= p->p[w].on;
        if (!playing) continue;
        float mix[SAMPLES];
        if (p->pick >= 0) {
            for (int w = 0; w < SAMPLES; w++) mix[w] = w == p->pick ? 1.f : 0.f;
        } else gains(v, mix);
        int age0 = p->age;
        for (int w = 0; w < SAMPLES; w++) {
            player_t *q = &p->p[w];
            if (!q->on) continue;
            int age = age0;
            for (int i = 0; i < frames; i++) {
                int k = (int)q->pos;
                if (k >= q->n - 1) { q->on = 0; break; }
                float fr = (float)(q->pos - k);
                float s = q->x[k] * (1.f - fr) + q->x[k + 1] * fr;
                float g = p->gain * (p->mixed[w] + (mix[w] - p->mixed[w]) * i / frames);   /* glides: no clicks */
                if (age < 64) g *= age / 64.f;
                if (p->fade) {
                    if (age >= p->fade) { q->on = 0; break; }
                    g *= 1.f - (float)age / p->fade;
                }
                out[i * VOICES + v] += s * g;
                q->pos += p->rate;
                age++;
            }
        }
        p->age = age0 + frames;
        for (int w = 0; w < SAMPLES; w++) p->mixed[w] = mix[w];
    }
}
