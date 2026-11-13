/*
 * Console's glue for 6W6 (the TR-606 from Schwung, by Charles Vestal; GPL-3.0, see 606/).
 * The engine is compiled whole into this file, so this can read each voice's sample before the engine
 * mixes them: Console records each drum onto its own track (MULTI) and does the panning, the reverb and
 * the delay itself, so the engine's own send effects and master stage aren't used.
 *
 * Built by build.sh: g++ -O2 -shared -fPIC -o lib606.so glue606.cpp
 */
#include "606/sd606_engine.cpp"
#include <cstdio>

#define VOICES SD606_NUM_VOICES
typedef sd606_engine_t engine_t;
static inline engine_t *create(float sr) { return sd606_create(sr); }
static inline void set_param(engine_t *e, const char *k, const char *v) { sd606_set_param(e, k, v); }
static inline int get_param(engine_t *e, const char *k, char *b, int n) { return sd606_get_param(e, k, b, n); }
static inline void trigger(engine_t *e, int v, int vel) { sd606_trigger(e, v, vel); }

/* Every voice's own sample, after its drive, level, velocity and choke, times the kit volume. */
static void render_voices(engine_t *e, float *out, int frames)
{
    const float vol = e->potv[e->p_volume];
    for(int i = 0; i < frames; ++i)
    {
        float *o = out + i * VOICES;
#define ONE(vid, expr) \
        do { float s = 0.0f; \
             if(e->rt[vid].choke_gain > 0.0f) s = voice_sample(e, vid, (expr)) * vol; \
             o[vid] = (s > -8.0f && s < 8.0f) ? s : 0.0f; } while(0)
        ONE(SD606_BD, e->bd.process());
        ONE(SD606_SD, e->sd.process());
        ONE(SD606_LT, e->lt.process());
        ONE(SD606_HT, e->ht.process());
        ONE(SD606_CH, e->ch.process());
        ONE(SD606_OH, e->oh.process());
        ONE(SD606_CY, e->cy.process());
        ONE(SD606_CP, e->cp.process());
#undef ONE
    }
}

#include "glue_common.h"
