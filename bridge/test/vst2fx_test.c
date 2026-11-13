/* Host test for vst2fx.so: loads the fake VST2 effect through it, as Console's module host does. */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct {
    uint32_t v; void *(*create)(const char *, const char *); void (*destroy)(void *); void (*process)(void *, int16_t *, int);
    void (*set)(void *, const char *, const char *); int (*get)(void *, const char *, char *, int); void *midi;
} api_t;
static int fails;
#define CHECK(c, m) do { if (c) printf("ok:   %s\n", m); else { printf("FAIL: %s\n", m); fails++; } } while (0)
int main(int argc, char **argv)
{
    if (argc < 4) return 2;
    char cmd[600];
    snprintf(cmd, sizeof cmd, "mkdir -p %s && printf 'file fakevst.so\\nknob 0 GAIN\\nknob 99 NOPE\\n' > %s/plugin.txt", argv[3], argv[3]);
    if (system(cmd)) return 2;
    setenv("CONSOLE_PLUGINS", argv[2], 1);
    void *dl = dlopen(argv[1], RTLD_NOW);
    if (!dl) { printf("%s\n", dlerror()); return 2; }
    const api_t *(*init)(const void *) = dlsym(dl, "move_audio_fx_init_v2");
    CHECK(init != NULL, "exports move_audio_fx_init_v2");
    const api_t *api = init(NULL);
    void *h = api->create(argv[3], NULL);
    CHECK(h != NULL, "loads the VST2 plugin named in plugin.txt");
    char js[2048];
    int n = api->get(h, "chain_params", js, sizeof js);
    printf("      %s\n", js);
    CHECK(n > 0 && strstr(js, "\"options\":[\"Clean\",\"Crunch hot\",\"Lead\"]") && strstr(js, "\"name\":\"GAIN\"") && !strstr(js, "NOPE"),
          "chain_params: the preset names (cleaned) and the knobs that exist");
    CHECK(strstr(js, "\"default\":0.500") != NULL, "a knob starts at the plugin's own value");
    int16_t b[256 * 2];
    for (int i = 0; i < 512; i++) b[i] = (int16_t)(i % 2 ? -16000 : 16000);
    api->process(h, b, 256);
    CHECK(b[0] == 8000 && b[1] == -8000 && b[510] == 8000, "audio goes through the plugin (x0.5), both channels, two blocks");
    api->set(h, "k1", "1.0");
    for (int i = 0; i < 512; i++) b[i] = 20000;
    api->process(h, b, 256);
    CHECK(b[0] == 20000, "a knob sets the plugin's parameter (k1 = 1.0: unity)");
    api->set(h, "preset", "Crunch hot");
    api->get(h, "x", js, 1);
    api->set(h, "preset", "Lead");
    for (int i = 0; i < 512; i++) b[i] = 20000;
    api->process(h, b, 256);
    CHECK(b[0] == 10000, "the preset is picked by its name");
    for (int i = 0; i < 512; i++) b[i] = 32767;
    api->set(h, "k1", "1.0"); api->set(h, "preset", "Clean");
    api->process(h, b, 100);
    CHECK(b[0] == 32767 && b[199] == 32767, "a block of 100 frames works too");
    api->destroy(h);
    CHECK(api->create("/nonexistent", NULL) == NULL, "no plugin.txt: no instance, no crash");
    printf(fails ? "FAILED\n" : "ALL PASSED\n");
    return fails != 0;
}
