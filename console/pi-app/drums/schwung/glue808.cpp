/*
 * Console's glue for 8W8 (the TR-808 from Schwung, by athousanddetails; GPL-3.0, see 808/).
 * As glue606.cpp: the engine is compiled whole into this file so each voice comes out on its own.
 *
 * Built by build.sh: g++ -O2 -shared -fPIC -o lib808.so glue808.cpp
 */
#include "808/w8_engine.cpp"
#include <cstdio>

#define VOICES W8_NUM_VOICES
typedef w8_engine_t engine_t;
static inline engine_t *create(float sr) { return w8_create(sr); }
static inline void set_param(engine_t *e, const char *k, const char *v) { w8_set_param(e, k, v); }
static inline int get_param(engine_t *e, const char *k, char *b, int n) { return w8_get_param(e, k, b, n); }
static inline void trigger(engine_t *e, int v, int vel) { w8_trigger(e, v, vel); }

static void render_voices(engine_t *e, float *out, int frames)
{
    const float vol = e->potv[e->p_volume];
    for(int i = 0; i < frames; ++i)
    {
        float *o = out + i * VOICES;
        for(int v = 0; v < VOICES; ++v) o[v] = 0.0f;
#define ONE(vid, obj) \
        do { if(e->rt[vid].choke_gain > 0.0f && e->obj.active()) \
                 o[vid] = voice_sample(e, vid, e->obj.process()) * vol; } while(0)
        ONE(W8_BD, bdc); ONE(W8_SD, sdc); ONE(W8_LT, ltc); ONE(W8_MT, mtc);
        ONE(W8_HT, htc); ONE(W8_LC, lcc); ONE(W8_MC, mcc); ONE(W8_HC, hcc);
        ONE(W8_RS, rs);  ONE(W8_CL, clc); ONE(W8_MA, mac); ONE(W8_CP, cpc);
        /* the shared metal bank ticks once a sample, always (it free-runs, as on the hardware) */
        const double mbus = e->mbank.tick();
        ONE(W8_CB, cbc);
#define METAL(vid, circ) \
        do { if(e->rt[vid].choke_gain > 0.0f && e->circ.active()) \
                 o[vid] = voice_sample(e, vid, e->circ.process(mbus)) * vol; } while(0)
        METAL(W8_CH, chc); METAL(W8_OH, ohc); METAL(W8_CY, cyc);
#undef METAL
#undef ONE
        for(int v = 0; v < VOICES; ++v) if(!(o[v] > -8.0f && o[v] < 8.0f)) o[v] = 0.0f;
    }
}

#include "glue_common.h"
