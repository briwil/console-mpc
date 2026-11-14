/* A tiny VST2 INSTRUMENT for testing vst2fx.so: a note on gives a steady tone (level * velocity), a note off silence.
   Parameter 0 "Level" (0.5 at the start), parameter 1 "Cutoff"; two programs. */
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef struct AEffect AEffect;
typedef intptr_t (*Master)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
struct AEffect {
    int32_t magic; intptr_t (*dispatcher)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
    void (*process)(AEffect *, float **, float **, int32_t); void (*setParameter)(AEffect *, int32_t, float); float (*getParameter)(AEffect *, int32_t);
    int32_t numPrograms, numParams, numInputs, numOutputs, flags; intptr_t r1, r2; int32_t d, q1, q2; float ratio; void *obj, *user; int32_t id, ver;
    void (*processReplacing)(AEffect *, float **, float **, int32_t);
};
typedef struct { int32_t type, byteSize, deltaFrames, flags, noteLength, noteOffset; char midi[4]; char detune, noteOffVel, r1, r2; } VstMidi;
typedef struct { int32_t numEvents; intptr_t reserved; VstMidi *events[64]; } VstEvents;
static float level = 0.5f, cutoff = 0.25f; static int prog, vel, started;
static intptr_t disp(AEffect *e, int32_t op, int32_t i, intptr_t v, void *p, float o)
{
    (void)e; (void)o;
    if (op == 71) started = 1;
    if (op == 2) prog = (int)v;
    if (op == 3) return prog;
    if (op == 8) { snprintf((char *)p, 24, i == 0 ? "Level" : "Cutoff"); return 1; }
    if (op == 29) { snprintf((char *)p, 24, i == 0 ? "Init" : "Bass"); return 1; }
    if (op == 25) {
        VstEvents *ev = p;
        for (int k = 0; k < ev->numEvents; k++) {
            VstMidi *m = ev->events[k];
            if (m->type != 1) continue;
            int st = m->midi[0] & 0xF0;
            if (st == 0x90 && m->midi[2] > 0) vel = m->midi[2];
            else if (st == 0x80 || st == 0x90) vel = 0;
        }
    }
    return 0;
}
static void rep(AEffect *e, float **in, float **out, int32_t n)
{
    (void)e; (void)in;
    for (int c = 0; c < 2; c++) for (int i = 0; i < n; i++) out[c][i] = started ? level * (vel / 127.0f) : 0.0f;
}
static void setp(AEffect *e, int32_t i, float v) { (void)e; if (i == 0) level = v; else cutoff = v; }
static float getp(AEffect *e, int32_t i) { (void)e; return i == 0 ? level : cutoff; }
static AEffect fx = { .magic = 0x56737450, .dispatcher = disp, .setParameter = setp, .getParameter = getp, .numPrograms = 2,
                      .numParams = 2, .numInputs = 0, .numOutputs = 2, .flags = 16 | 256, .processReplacing = rep };
AEffect *VSTPluginMain(Master m) { (void)m; return &fx; }
