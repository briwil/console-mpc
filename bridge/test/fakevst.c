/* A tiny VST2 effect for testing vst2fx.so: halves the sound (parameter 0 = gain, 0.5 at the start), 3 presets. */
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
static float gain = 0.5f; static int prog; static int opened, mains;
static intptr_t disp(AEffect *e, int32_t op, int32_t i, intptr_t v, void *p, float o)
{
    (void)e; (void)o;
    if (op == 0) opened = 1;
    if (op == 12) mains = (int)v;
    if (op == 2) prog = (int)v;
    if (op == 3) return prog;
    if (op == 29) { snprintf((char *)p, 24, i == 0 ? "Clean" : i == 1 ? "Crunch \"hot\"" : "Lead"); return 1; }
    return 0;
}
static void rep(AEffect *e, float **in, float **out, int32_t n)
{
    (void)e;
    for (int c = 0; c < 2; c++) for (int i = 0; i < n; i++) out[c][i] = in[c][i] * gain * (prog == 2 ? 0.5f : 1.0f);
}
static void setp(AEffect *e, int32_t i, float v) { (void)e; if (i == 0) gain = v; }
static float getp(AEffect *e, int32_t i) { (void)e; return i == 0 ? gain : 0; }
static AEffect fx = { .magic = 0x56737450, .dispatcher = disp, .setParameter = setp, .getParameter = getp, .numPrograms = 3,
                      .numParams = 2, .numInputs = 2, .numOutputs = 2, .flags = 16, .processReplacing = rep };
AEffect *VSTPluginMain(Master m) { (void)m; return &fx; }
int fake_state(void) { return opened * 10 + mains; }
