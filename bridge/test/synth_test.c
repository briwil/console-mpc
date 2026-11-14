/* Host test for vst2fx.so as an INSTRUMENT host: notes in, sound out, knobs named by the plugin, as Console's module host drives it. */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { uint32_t v; int sr, fpb; uint8_t *mem; int out_off, in_off; } host_t;
typedef struct {
    uint32_t v; void *(*create)(const char *, const char *); void (*destroy)(void *); void (*midi)(void *, const uint8_t *, int, int);
    void (*set)(void *, const char *, const char *); int (*get)(void *, const char *, char *, int); int (*err)(void *, char *, int);
    void (*render)(void *, int16_t *, int);
} inst_t;
static int fails;
#define CHECK(c, m) do { if (c) printf("ok:   %s\n", m); else { printf("FAIL: %s\n", m); fails++; } } while (0)
int main(int argc, char **argv)
{
    if (argc < 4) return 2;
    char cmd[600];
    snprintf(cmd, sizeof cmd, "mkdir -p %s && printf 'file fakesynth.so\\ninstrument 1\\nknob 0\\nknob 1\\nknob 7 GONE\\n' > %s/plugin.txt", argv[3], argv[3]);
    if (system(cmd)) return 2;
    setenv("CONSOLE_PLUGINS", argv[2], 1);
    void *dl = dlopen(argv[1], RTLD_NOW);
    if (!dl) { printf("%s\n", dlerror()); return 2; }
    const inst_t *(*init)(const host_t *) = dlsym(dl, "move_plugin_init_v2");
    host_t host = { 2, 44100, 128, NULL, 0, 0 };
    const inst_t *api = init(&host);
    CHECK(api && api->midi && api->render, "the instrument API has on_midi and render_block");
    void *h = api->create(argv[3], NULL);
    CHECK(h != NULL, "an instrument plugin (no audio inputs) loads");
    char js[2048];
    api->get(h, "chain_params", js, sizeof js);
    printf("      %s\n", js);
    CHECK(strstr(js, "\"name\":\"LEVEL\"") && strstr(js, "\"name\":\"CUTOFF\"") && !strstr(js, "GONE"),
          "knobs without a label take the plugin's own names (upper case); a missing parameter is left out");
    int16_t b[256];
    memset(b, 1, sizeof b);
    api->render(h, b, 128);
    CHECK(b[0] == 0 && b[255] == 0, "no note: silence");
    const uint8_t on[3] = { 0x90, 60, 127 }, off[3] = { 0x80, 60, 0 };
    api->midi(h, on, 3, 0);
    api->render(h, b, 128);
    CHECK(b[0] > 16000 && b[0] < 16500 && b[1] == b[0] && b[255] == b[0], "note on: a tone at level 0.5 x velocity, both channels");
    api->set(h, "k1", "1.0");
    api->render(h, b, 128);
    CHECK(b[0] > 32000, "a knob (k1 = level) changes it");
    char v[32];
    api->get(h, "k1", v, sizeof v);
    CHECK(!strcmp(v, "1.000"), "a knob's value can be read back");
    api->midi(h, off, 3, 0);
    api->render(h, b, 128);
    CHECK(b[0] == 0, "note off: silence");
    api->set(h, "preset", "Bass");
    api->get(h, "preset", v, sizeof v);
    CHECK(!strcmp(v, "Bass"), "the preset is chosen and read back by name");
    api->destroy(h);
    /* presets listed in plugin.txt (plugins that keep their own list out of reach): names offered, values applied by parameter */
    snprintf(cmd, sizeof cmd, "printf 'file fakesynth.so\\ninstrument 1\\nknob 0\\npreset Quiet|0=0.1\\npreset Loud|0=1.0 1=0.5\\n' > %s/plugin.txt", argv[3]);
    if (system(cmd)) return 2;
    h = api->create(argv[3], NULL);
    api->get(h, "chain_params", js, sizeof js);
    CHECK(strstr(js, "\"options\":[\"Quiet\",\"Loud\"]") != NULL, "presets from plugin.txt are the preset list");
    api->set(h, "preset", "Loud");
    api->midi(h, on, 3, 0);
    api->render(h, b, 128);
    CHECK(b[0] > 32000, "choosing one sets its parameter values");
    api->set(h, "preset", "Quiet");
    api->render(h, b, 128);
    CHECK(b[0] > 3000 && b[0] < 4500, "and another preset changes them");
    api->destroy(h);
    setenv("CONSOLE_PLUGINS", "/nonexistent", 1);
    CHECK(api->create(argv[3], NULL) == NULL, "no plugin file: no instance");
    char e[200];
    api->err(NULL, e, sizeof e);
    CHECK(strstr(e, "FAKESYNTH.SO IS NOT THERE") != NULL, "and the error names the file");
    printf(fails ? "FAILED\n" : "ALL PASSED\n");
    return fails != 0;
}
