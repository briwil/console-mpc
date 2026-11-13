/* vst2fx.so: lets Console use a VST2 audio effect (such as Stompbox) as an insert effect.
 *
 * It is a Schwung "audio_fx" module (audio_fx_api_v2: create_instance, process_block, set_param, get_param) that loads
 * the VST2 plugin file named in plugin.txt (next to it, in the module folder) and plays the host's part: the sample
 * rate and block size, one stereo in and out. Console's insert page then shows the plugin's PRESET and a few of its
 * knobs (chain_params, built here from plugin.txt).
 *
 * plugin.txt:   file stompbox.so            the VST2 plugin: looked for in $CONSOLE_PLUGINS, then in the module folder
 *               knob 74 AMP 1               a knob on the insert page: the VST parameter's number, then its label
 *               (up to 7 knobs; the first knob of the page is always the plugin's PRESET list)
 *
 * Built like the bridge (no headers, no libraries): see bridge/build.sh. The VST2 interface used here is the plain,
 * public one: AEffect and its dispatcher, written out below from the format's layout.
 */
#include <stdint.h>
#include <stddef.h>

/* ---- the little bit of libc used (declared by hand: the build has no headers) ---- */
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern int dlclose(void *);
extern void *calloc(size_t, size_t);
extern void free(void *);
extern char *getenv(const char *);
extern int open(const char *, int, ...);
extern long read(int, void *, unsigned long);
extern int close(int);
extern long write(int, const void *, unsigned long);
extern int unlink(const char *);
extern int getpid(void);
extern int snprintf(char *, size_t, const char *, ...);
extern size_t strlen(const char *);
extern int strcmp(const char *, const char *);
extern int strncmp(const char *, const char *, size_t);
extern double strtod(const char *, char **);
extern void *memset(void *, int, size_t);
extern void *memcpy(void *, const void *, size_t);
#define RTLD_NOW 2

/* ---- VST2 ---- */
typedef struct AEffect AEffect;
typedef intptr_t (*Master)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
typedef intptr_t (*Dispatch)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
typedef void (*Process)(AEffect *, float **, float **, int32_t);
typedef void (*SetParam)(AEffect *, int32_t, float);
typedef float (*GetParam)(AEffect *, int32_t);
struct AEffect {
    int32_t magic;                       /* 'VstP' */
    Dispatch dispatcher;
    Process process;
    SetParam setParameter;
    GetParam getParameter;
    int32_t numPrograms, numParams, numInputs, numOutputs, flags;
    intptr_t resvd1, resvd2;
    int32_t initialDelay, realQualities, offQualities;
    float ioRatio;
    void *object, *user;
    int32_t uniqueID, version;
    Process processReplacing;
};
#define VST_MAGIC 0x56737450
#define FLAG_REPLACING 16
enum { eOpen = 0, eClose = 1, eSetProgram = 2, eGetProgram = 3, eSetRate = 10, eSetBlock = 11, eMains = 12,
       eProgramNameIndexed = 29 };
enum { mVersion = 1, mRate = 16, mBlock = 17, mLevel = 23, mVendor = 32, mProduct = 33, mVendorVer = 34 };

typedef AEffect *(*Entry)(Master);

/* ---- the Schwung audio_fx v2 table (as in audio_fx_api_v2.h) ---- */
typedef struct {
    uint32_t api_version;
    void *(*create_instance)(const char *module_dir, const char *config_json);
    void (*destroy_instance)(void *);
    void (*process_block)(void *, int16_t *, int);
    void (*set_param)(void *, const char *, const char *);
    int (*get_param)(void *, const char *, char *, int);
    void (*on_midi)(void *, const uint8_t *, int, int);
} fx_api_t;

#define BLOCK 128
#define MAXK 7
#define MAXP 128

typedef struct {
    void *dl;
    AEffect *e;
    int nk, kidx[MAXK];
    char klabel[MAXK][16];
    int npre;                            /* presets the plugin lists */
    int prog;                            /* the preset last chosen (set_param) */
    int pfirst, pcount;                  /* the presets offered: pcount from pfirst (plugin.txt: presets FIRST COUNT); 0 = all */
    float lin[BLOCK], rin[BLOCK], lout[BLOCK], rout[BLOCK];
} inst_t;

static intptr_t master(AEffect *e, int32_t op, int32_t idx, intptr_t val, void *ptr, float opt)
{
    (void)e; (void)idx; (void)val; (void)opt;
    switch (op) {
    case mVersion: return 2400;
    case mRate: return 44100;
    case mBlock: return BLOCK;
    case mLevel: return 2;               /* realtime */
    case mVendor: if (ptr) snprintf((char *)ptr, 64, "Console"); return 1;
    case mProduct: if (ptr) snprintf((char *)ptr, 64, "Console"); return 1;
    case mVendorVer: return 1;
    default: return 0;               /* time info (none), automate, idle ...: nothing */
    }
}

static int readfile(const char *path, char *buf, int n)
{
    int fd = open(path, 0);
    if (fd < 0) return -1;
    long got = read(fd, buf, (unsigned long)(n - 1));
    close(fd);
    if (got < 0) return -1;
    buf[got] = 0;
    return (int)got;
}

/* Every instance loads its own copy of the plugin file, so two of them (an insert and the GUITAR instrument) never share the
 * plugin's global state (the same file loaded twice is one library to the loader). The copy is removed at once. */
static int preset_name(inst_t *s, int i, char *out);
static void *open_private(const char *path)
{
    static int count;
    char tmp[600];
    static char buf[65536];
    snprintf(tmp, sizeof tmp, "%s.%d.%d.tmp.so", path, getpid(), ++count);
    int in = open(path, 0), out = in < 0 ? -1 : open(tmp, 0x241, 0755);
    void *dl = NULL;
    if (out >= 0) {
        long n, ok = 1;
        while ((n = read(in, buf, sizeof buf)) > 0)
            if (write(out, buf, (unsigned long)n) != n) { ok = 0; break; }
        close(out);
        if (ok && n == 0) dl = dlopen(tmp, RTLD_NOW);
        unlink(tmp);
    }
    if (in >= 0) close(in);
    return dl ? dl : dlopen(path, RTLD_NOW);
}

static void *create(const char *dir, const char *cfg)
{
    (void)cfg;
    char path[512], text[2048], file[128] = "";
    snprintf(path, sizeof path, "%s/plugin.txt", dir);
    if (readfile(path, text, sizeof text) < 0) return NULL;
    inst_t *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    for (char *p = text; *p;) {
        char *eol = p;
        while (*eol && *eol != '\n') eol++;
        char save = *eol;
        *eol = 0;
        if (!strncmp(p, "file ", 5)) snprintf(file, sizeof file, "%s", p + 5);
        else if (!strncmp(p, "presets ", 8)) { char *e2; s->pfirst = (int)strtod(p + 8, &e2); s->pcount = (int)strtod(e2, NULL); }
        else if (!strncmp(p, "knob ", 5) && s->nk < MAXK) {
            char *end;
            int idx = (int)strtod(p + 5, &end);
            while (*end == ' ') end++;
            s->kidx[s->nk] = idx;
            snprintf(s->klabel[s->nk], sizeof s->klabel[0], "%s", end);
            s->nk++;
        }
        *eol = save;
        p = save ? eol + 1 : eol;
    }
    if (!file[0]) { free(s); return NULL; }
    const char *pd = getenv("CONSOLE_PLUGINS");
    s->dl = NULL;
    if (pd && pd[0]) {
        snprintf(path, sizeof path, "%s/%s", pd, file);
        s->dl = open_private(path);
    }
    if (!s->dl) {
        snprintf(path, sizeof path, "%s/%s", dir, file);
        s->dl = dlopen(path, RTLD_NOW);
    }
    if (!s->dl) { free(s); return NULL; }
    Entry entry = (Entry)dlsym(s->dl, "VSTPluginMain");
    if (!entry) entry = (Entry)dlsym(s->dl, "main");
    AEffect *e = entry ? entry(master) : NULL;
    if (!e || e->magic != VST_MAGIC || !e->dispatcher || !(e->flags & FLAG_REPLACING) || !e->processReplacing
        || e->numInputs < 1 || e->numOutputs < 1) {
        dlclose(s->dl); free(s); return NULL;
    }
    s->e = e;
    e->dispatcher(e, eOpen, 0, 0, NULL, 0);
    e->dispatcher(e, eSetRate, 0, 0, NULL, 44100.0f);
    e->dispatcher(e, eSetBlock, 0, BLOCK, NULL, 0);
    e->dispatcher(e, eMains, 0, 1, NULL, 0);
    s->npre = e->numPrograms;
    if (s->pfirst < 0 || s->pfirst >= s->npre) s->pfirst = 0;
    if (s->pcount <= 0 || s->pfirst + s->pcount > s->npre) s->pcount = s->npre - s->pfirst;
    s->prog = s->pfirst;
    if (s->npre > 0) e->dispatcher(e, eSetProgram, 0, s->prog, NULL, 0);
    {
        char m[400], nm[40];
        int n = snprintf(m, sizeof m, "vst2fx: %d presets, first:", s->npre);
        for (int i = 0; i < s->npre && i < 6 && n < 300; i++) { preset_name(s, i, nm); n += snprintf(m + n, sizeof m - (size_t)n, " [%s]", nm); }
        m[n++] = '\n';
        write(2, m, (unsigned long)n);
    }
     /* the first preset is loaded (a plugin that starts with an empty chain is silent) */
    for (int k = 0; k < s->nk; k++)
        if (s->kidx[k] < 0 || s->kidx[k] >= e->numParams) s->kidx[k] = -1;
    return s;
}

static void destroy(void *h)
{
    inst_t *s = h;
    if (!s) return;
    s->e->dispatcher(s->e, eMains, 0, 0, NULL, 0);
    s->e->dispatcher(s->e, eClose, 0, 0, NULL, 0);
    dlclose(s->dl);
    free(s);
}

static int16_t clip(float x)
{
    x *= 32768.0f;
    if (x > 32767.0f) return 32767;
    if (x < -32768.0f) return -32768;
    return (int16_t)x;
}

static void process(void *h, int16_t *io, int frames)
{
    inst_t *s = h;
    AEffect *e = s->e;
    for (int done = 0; done < frames; done += BLOCK) {
        int n = frames - done < BLOCK ? frames - done : BLOCK;
        int16_t *p = io + done * 2;
        for (int i = 0; i < n; i++) { s->lin[i] = p[2 * i] / 32768.0f; s->rin[i] = p[2 * i + 1] / 32768.0f; }
        float *in[2] = { s->lin, s->rin }, *out[2] = { s->lout, s->rout };
        memset(s->lout, 0, sizeof s->lout);
        memset(s->rout, 0, sizeof s->rout);
        e->processReplacing(e, in, out, n);
        for (int i = 0; i < n; i++) { p[2 * i] = clip(s->lout[i]); p[2 * i + 1] = clip(e->numOutputs > 1 ? s->rout[i] : s->lout[i]); }
    }
}

static int preset_name(inst_t *s, int i, char *out)
{
    char buf[256];
    memset(buf, 0, sizeof buf);
    s->e->dispatcher(s->e, eProgramNameIndexed, i, 0, buf, 0);
    if (!buf[0]) snprintf(buf, sizeof buf, "Preset %d", i + 1);
    int j = 0;                                   /* (quotes, backslashes and control characters out: the name goes into JSON) */
    for (int c = 0; buf[c] && j < 39; c++)
        if (buf[c] != '"' && buf[c] != '\\' && (unsigned char)buf[c] >= 32) out[j++] = buf[c];
    out[j] = 0;
    return 1;
}

static void set_param(void *h, const char *key, const char *val)
{
    inst_t *s = h;
    if (!strcmp(key, "preset")) {
        char nm[40];
        for (int i = s->pfirst; i < s->pfirst + s->pcount; i++) {
            preset_name(s, i, nm);
            if (!strcmp(nm, val)) {
                s->prog = i;
                s->e->dispatcher(s->e, eSetProgram, 0, i, NULL, 0);
                char m[100]; int n = snprintf(m, sizeof m, "vst2fx: preset %d [%s]\n", i, nm); write(2, m, (unsigned long)n);
                return;
            }
        }
        return;
    }
    if (key[0] == 'k' && key[1] >= '1' && key[1] <= '7' && !key[2]) {
        int k = key[1] - '1';
        if (k < s->nk && s->kidx[k] >= 0) {
            float v = (float)strtod(val, NULL);
            if (v < 0) v = 0;
            if (v > 1) v = 1;
            s->e->setParameter(s->e, s->kidx[k], v);
        }
    }
}

static int get_param(void *h, const char *key, char *buf, int len)
{
    inst_t *s = h;
    if (strcmp(key, "chain_params")) return -1;
    int n = snprintf(buf, (size_t)len, "[{\"key\":\"preset\",\"name\":\"PRESET\",\"type\":\"enum\",\"default\":0,\"options\":[");
    int cur = (int)s->e->dispatcher(s->e, eGetProgram, 0, 0, NULL, 0);
    for (int i = s->pfirst; i < s->pfirst + s->pcount && n < len - 80; i++) {
        char nm[40];
        preset_name(s, i, nm);
        n += snprintf(buf + n, (size_t)(len - n), "%s\"%s\"", i > s->pfirst ? "," : "", nm);
    }
    n += snprintf(buf + n, (size_t)(len - n), "]}");
    for (int k = 0; k < s->nk && n < len - 120; k++) {
        if (s->kidx[k] < 0) continue;
        float d = s->e->getParameter(s->e, s->kidx[k]);
        n += snprintf(buf + n, (size_t)(len - n),
                      ",{\"key\":\"k%d\",\"name\":\"%s\",\"type\":\"float\",\"min\":0,\"max\":1,\"step\":0.02,\"default\":%d.%03d}",
                      k + 1, s->klabel[k], (int)d, (int)((d - (int)d) * 1000));
    }
    (void)cur;
    if (n < len - 2) { buf[n++] = ']'; buf[n] = 0; }
    return n;
}

static const fx_api_t api = { 2, create, destroy, process, set_param, get_param, NULL };

/* ---- the same plugin as an INSTRUMENT (the GUITAR instrument): it plays the audio input through the plugin ----
 * The host (schwung/host.c) hands each module its block of the audio input at mapped_memory + audio_in_offset
 * (128 frames, interleaved int16 stereo, as on the Move). The start of host_api_v1_t, as in plugin_api_v1.h: */
typedef struct { uint32_t api_version; int sample_rate, frames_per_block; uint8_t *mapped_memory; int audio_out_offset, audio_in_offset; } host_t;
static const host_t *the_host;

typedef struct {
    uint32_t api_version;
    void *(*create_instance)(const char *, const char *);
    void (*destroy_instance)(void *);
    void (*on_midi)(void *, const uint8_t *, int, int);
    void (*set_param)(void *, const char *, const char *);
    int (*get_param)(void *, const char *, char *, int);
    int (*get_error)(void *, char *, int);
    void (*render_block)(void *, int16_t *, int);
} inst_api_t;

static void render_block(void *h, int16_t *out, int frames)
{
    if (!the_host || !the_host->mapped_memory || frames > BLOCK) return;
    memcpy(out, the_host->mapped_memory + the_host->audio_in_offset, (size_t)frames * 4);
    static int blocks;                                   /* the plugin only wakes up on a preset change made while it runs: */
    inst_t *gi = h;                                      /* go to the second preset a moment after the start, then back to the first */
    if (++blocks == 20 && gi->pcount > 1) gi->e->dispatcher(gi->e, eSetProgram, 0, gi->prog + 1 < gi->pfirst + gi->pcount ? gi->prog + 1 : gi->prog - 1, NULL, 0);
    if (blocks == 60 && gi->npre > 0) gi->e->dispatcher(gi->e, eSetProgram, 0, gi->prog, NULL, 0);
    static int calls, pin, pout;                         /* a check line every ~3 s in the log: what goes in and out of the plugin */
    for (int i = 0; i < frames * 2; i++) { int a = out[i] < 0 ? -out[i] : out[i]; if (a > pin) pin = a; }
    process(h, out, frames);
    for (int i = 0; i < frames * 2; i++) { int a = out[i] < 0 ? -out[i] : out[i]; if (a > pout) pout = a; }
    if (++calls >= 1000) {
        char m[120];
        int n = snprintf(m, sizeof m, "guitar plugin: in %d, out %d (of 32767)\n", pin, pout);
        write(2, m, (unsigned long)n);
        calls = pin = pout = 0;
    }
}

static int get_error(void *h, char *buf, int len)
{
    if (h) { if (len > 0) buf[0] = 0; return 0; }          /* a running instance has no error */
    snprintf(buf, (size_t)len, "STOMPBOX IS NOT THERE: PUT stompbox.so IN ConsoleData/plugins");
    return 1;
}

static const inst_api_t inst_api = { 2, create, destroy, NULL, set_param, get_param, get_error, render_block };

__attribute__((visibility("default"))) const inst_api_t *move_plugin_init_v2(const host_t *host)
{
    the_host = host;
    return &inst_api;
}

__attribute__((visibility("default"))) const fx_api_t *move_audio_fx_init_v2(const void *host)
{
    (void)host;
    return &api;
}
