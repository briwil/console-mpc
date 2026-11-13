/* Console's host for Schwung sound generators (Ableton Move modules): loads a module's dsp.so and runs it.
 *
 * Every module in Schwung's catalog speaks the same plugin API (plugin_api_v1.h, from Schwung, MIT):
 * move_plugin_init_v2() hands back create_instance / on_midi / set_param / get_param / render_block.
 * This file is the "host" side of that, cut down to what Console needs: no shared memory with Move's
 * firmware, no chain, no MIDI out. modules.py calls these through ctypes:
 *
 *   sh_open(dsp_path, module_dir, defaults_json) -> handle, or NULL (sh_error says why)
 *   sh_midi(h, b0, b1, b2)                       a 3-byte MIDI message (note on / off, CC...)
 *   sh_set(h, key, value)                        a setting, as text (the API's way)
 *   sh_get(h, key, buf, len)                     a setting's value as text; < 0 if it has none
 *   sh_render(h, out, frames)                    out: frames x 2 floats (left, right)
 *   sh_module_error(h, buf, len)                 what's wrong, if the module says (a missing ROM...)
 *   sh_close(h)
 *   sh_bpm(bpm)                                  the song's tempo, for modules that follow it
 *
 * Threads: the sound core renders / processes on its own thread while the app sets knobs, sends notes and
 * closes modules from another. Many modules aren't written for that (a setting can reallocate a buffer the
 * audio is in the middle of using): it corrupted memory and crashed Console later. So every call into a
 * module instance holds that instance's lock (they're short; the sound waits a few microseconds at most).
 *
 * Modules are written for 128-frame blocks at 44.1 kHz (Move's), so sh_render always calls them with
 * 128 frames and keeps what's left over for the next call.
 */
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plugin_api_v1.h"
#include "audio_fx_api_v2.h"

#define BLOCK MOVE_FRAMES_PER_BLOCK

typedef struct {
    plugin_api_v2_t *api;
    void *inst;
    int16_t block[BLOCK * 2];
    int left;               /* frames of block not handed out yet */
    pthread_mutex_t lock;   /* one call into the module at a time (see Threads, above) */
} handle_t;

static uint8_t shared_mem[16384];   /* Move's mapped memory: here just zeros (no audio in) */
static host_api_v1_t host;          /* zeroed: every callback we don't give is NULL, as the API expects */
static float song_bpm = 120.0f;
static char last_error[512];

static void host_log(const char *msg) { (void)msg; }
static int no_midi(const uint8_t *msg, int len) { (void)msg; (void)len; return 0; }
static int clock_status(void) { return MOVE_CLOCK_STATUS_UNAVAILABLE; }
static float get_bpm(void) { return song_bpm; }

static void init_host(void)
{
    if (host.api_version)
        return;
    host.api_version = MOVE_PLUGIN_API_VERSION;
    host.sample_rate = MOVE_SAMPLE_RATE;
    host.frames_per_block = BLOCK;
    host.mapped_memory = shared_mem;
    host.audio_out_offset = MOVE_AUDIO_OUT_OFFSET;
    host.audio_in_offset = MOVE_AUDIO_IN_OFFSET;
    host.log = host_log;
    host.midi_send_internal = no_midi;
    host.midi_send_external = no_midi;
    host.get_clock_status = clock_status;
    host.get_bpm = get_bpm;
}

const char *sh_error(void) { return last_error; }

void sh_bpm(float bpm) { if (bpm > 0) song_bpm = bpm; }

void *sh_open(const char *dsp_path, const char *module_dir, const char *defaults)
{
    init_host();
    last_error[0] = 0;
    void *dl = dlopen(dsp_path, RTLD_NOW | RTLD_LOCAL);
    if (!dl) {
        snprintf(last_error, sizeof last_error, "%s", dlerror());
        return NULL;
    }
    move_plugin_init_v2_fn init = (move_plugin_init_v2_fn)dlsym(dl, MOVE_PLUGIN_INIT_V2_SYMBOL);
    if (!init) {
        snprintf(last_error, sizeof last_error, "no %s in %s", MOVE_PLUGIN_INIT_V2_SYMBOL, dsp_path);
        return NULL;
    }
    plugin_api_v2_t *api = init(&host);
    if (!api || !api->create_instance || !api->render_block) {
        snprintf(last_error, sizeof last_error, "the module didn't start");
        return NULL;
    }
    void *inst = api->create_instance(module_dir, defaults && defaults[0] ? defaults : NULL);
    if (!inst) {
        if (api->get_error)
            api->get_error(NULL, last_error, sizeof last_error);
        if (!last_error[0])
            snprintf(last_error, sizeof last_error, "the module couldn't make an instance");
        return NULL;
    }
    handle_t *h = calloc(1, sizeof *h);
    h->api = api;
    h->inst = inst;
    pthread_mutex_init(&h->lock, NULL);
    return h;
}

int sh_module_error(handle_t *h, char *buf, int len)
{
    if (!h || !h->api->get_error || len <= 0)
        return 0;
    buf[0] = 0;
    pthread_mutex_lock(&h->lock);
    int n = h->api->get_error(h->inst, buf, len);
    pthread_mutex_unlock(&h->lock);
    return n;
}

void sh_close(handle_t *h)
{
    if (!h)
        return;
    pthread_mutex_lock(&h->lock);
    if (h->api->destroy_instance)
        h->api->destroy_instance(h->inst);
    pthread_mutex_unlock(&h->lock);
    pthread_mutex_destroy(&h->lock);
    free(h);
}

void sh_midi(handle_t *h, int b0, int b1, int b2)
{
    if (!h || !h->api->on_midi)
        return;
    uint8_t msg[3] = {(uint8_t)b0, (uint8_t)b1, (uint8_t)b2};
    int len = (b0 & 0xF0) == 0xC0 || (b0 & 0xF0) == 0xD0 ? 2 : 3;
    pthread_mutex_lock(&h->lock);
    h->api->on_midi(h->inst, msg, len, MOVE_MIDI_SOURCE_INTERNAL);
    pthread_mutex_unlock(&h->lock);
}

void sh_set(handle_t *h, const char *key, const char *val)
{
    if (h && h->api->set_param) {
        pthread_mutex_lock(&h->lock);
        h->api->set_param(h->inst, key, val);
        pthread_mutex_unlock(&h->lock);
    }
}

int sh_get(handle_t *h, const char *key, char *buf, int len)
{
    if (!h || !h->api->get_param || len <= 0)
        return -1;
    buf[0] = 0;
    pthread_mutex_lock(&h->lock);
    int n = h->api->get_param(h->inst, key, buf, len);
    pthread_mutex_unlock(&h->lock);
    return n;
}

void sh_render(handle_t *h, float *out, int frames)
{
    if (!h)
        return;
    int done = 0;
    pthread_mutex_lock(&h->lock);
    while (done < frames) {
        if (h->left == 0) {
            memset(h->block, 0, sizeof h->block);
            h->api->render_block(h->inst, h->block, BLOCK);
            h->left = BLOCK;
        }
        int n = frames - done < h->left ? frames - done : h->left;
        const int16_t *src = h->block + (BLOCK - h->left) * 2;
        for (int i = 0; i < n * 2; ++i)
            out[done * 2 + i] = src[i] * (1.0f / 32768.0f);
        done += n;
        h->left -= n;
    }
    pthread_mutex_unlock(&h->lock);
}


/* ---------------------------------------------------------------- audio effects (Schwung audio_fx modules)
 *   sh_fx_open(so_path, module_dir, defaults) -> handle or NULL     sh_fx_close(h)
 *   sh_fx_set / sh_fx_get / sh_fx_midi                                as for sound generators
 *   sh_fx_process(h, left, right, frames)  processes float buffers in place (the mix bus)
 */
typedef struct { audio_fx_api_v2_t *api; void *inst; pthread_mutex_t lock; } fx_t;

void *sh_fx_open(const char *so_path, const char *module_dir, const char *defaults)
{
    init_host();
    last_error[0] = 0;
    void *dl = dlopen(so_path, RTLD_NOW | RTLD_LOCAL);
    if (!dl) { snprintf(last_error, sizeof last_error, "%s", dlerror()); return NULL; }
    audio_fx_init_v2_fn init = (audio_fx_init_v2_fn)dlsym(dl, AUDIO_FX_INIT_V2_SYMBOL);
    if (!init) { snprintf(last_error, sizeof last_error, "no %s in %s", AUDIO_FX_INIT_V2_SYMBOL, so_path); return NULL; }
    audio_fx_api_v2_t *api = init(&host);
    if (!api || !api->create_instance || !api->process_block) {
        snprintf(last_error, sizeof last_error, "the effect didn't start"); return NULL;
    }
    void *inst = api->create_instance(module_dir, defaults && defaults[0] ? defaults : NULL);
    if (!inst) { snprintf(last_error, sizeof last_error, "the effect couldn't make an instance"); return NULL; }
    fx_t *f = calloc(1, sizeof *f);
    f->api = api;
    f->inst = inst;
    pthread_mutex_init(&f->lock, NULL);
    return f;
}

void sh_fx_close(fx_t *f)
{
    if (!f) return;
    pthread_mutex_lock(&f->lock);
    if (f->api->destroy_instance) f->api->destroy_instance(f->inst);
    pthread_mutex_unlock(&f->lock);
    pthread_mutex_destroy(&f->lock);
    free(f);
}

void sh_fx_set(fx_t *f, const char *key, const char *val)
{
    if (f && f->api->set_param) {
        pthread_mutex_lock(&f->lock);
        f->api->set_param(f->inst, key, val);
        pthread_mutex_unlock(&f->lock);
    }
}

int sh_fx_get(fx_t *f, const char *key, char *buf, int len)
{
    if (!f || !f->api->get_param || len <= 0) return -1;
    buf[0] = 0;
    pthread_mutex_lock(&f->lock);
    int n = f->api->get_param(f->inst, key, buf, len);
    pthread_mutex_unlock(&f->lock);
    return n;
}

void sh_fx_midi(fx_t *f, int b0, int b1, int b2)
{
    if (!f || !f->api->on_midi) return;
    uint8_t msg[3] = {(uint8_t)b0, (uint8_t)b1, (uint8_t)b2};
    pthread_mutex_lock(&f->lock);
    f->api->on_midi(f->inst, msg, 3, MOVE_MIDI_SOURCE_INTERNAL);
    pthread_mutex_unlock(&f->lock);
}

void sh_fx_process(fx_t *f, float *l, float *r, int frames)
{
    if (!f) return;
    int16_t blk[BLOCK * 2];
    pthread_mutex_lock(&f->lock);
    for (int done = 0; done < frames; done += BLOCK) {
        int n = frames - done < BLOCK ? frames - done : BLOCK;
        for (int i = 0; i < n; i++) {
            float a = l[done + i] * 32768.0f, b = r[done + i] * 32768.0f;
            blk[i * 2] = (int16_t)(a > 32767 ? 32767 : a < -32768 ? -32768 : a);
            blk[i * 2 + 1] = (int16_t)(b > 32767 ? 32767 : b < -32768 ? -32768 : b);
        }
        f->api->process_block(f->inst, blk, n);
        for (int i = 0; i < n; i++) {
            l[done + i] = blk[i * 2] * (1.0f / 32768.0f);
            r[done + i] = blk[i * 2 + 1] * (1.0f / 32768.0f);
        }
    }
    pthread_mutex_unlock(&f->lock);
}
