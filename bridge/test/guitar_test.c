/* Host test for the GUITAR instrument: schwung/host.c hands the audio input to vst2fx.so (as an instrument), which plays it through the fake VST2 effect. */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int fails;
#define CHECK(c, m) do { if (c) printf("ok:   %s\n", m); else { printf("FAIL: %s\n", m); fails++; } } while (0)
int main(int argc, char **argv)
{
    if (argc < 4) return 2;
    char cmd[600];
    snprintf(cmd, sizeof cmd, "mkdir -p %s && printf 'file fakevst.so\\nknob 0 GAIN\\n' > %s/plugin.txt", argv[3], argv[3]);
    if (system(cmd)) return 2;
    setenv("CONSOLE_PLUGINS", argv[2], 1);
    void *host = dlopen(argv[1], RTLD_NOW);
    if (!host) { printf("%s\n", dlerror()); return 2; }
    void *(*open_)(const char *, const char *, const char *) = dlsym(host, "sh_open");
    void (*render)(void *, float *, int) = dlsym(host, "sh_render");
    void (*setin)(const float *, const float *, int) = dlsym(host, "sh_set_input");
    const char *(*err)(void) = dlsym(host, "sh_error");
    char so[600]; snprintf(so, sizeof so, "%s/vst2fx.so", argv[4]);
    void *h = open_(so, argv[3], "");
    CHECK(h != NULL, "the host opens vst2fx.so as an instrument");
    if (!h) { printf("%s\\n", err()); return 1; }
    float l[256], r[256], out[256 * 2];
    for (int i = 0; i < 256; i++) { l[i] = 0.4f; r[i] = -0.4f; }
    setin(l, r, 256);
    render(h, out, 128);
    CHECK(out[0] > 0.19f && out[0] < 0.21f && out[1] < -0.19f && out[1] > -0.21f, "the audio input comes out through the plugin (x0.5)");
    render(h, out, 128);
    CHECK(out[2 * 127] > 0.19f && out[2 * 127] < 0.21f, "the second 128 frames of the cycle too");
    for (int i = 0; i < 256; i++) { l[i] = 0.0f; r[i] = 0.0f; }
    setin(l, r, 256);
    render(h, out, 128);
    CHECK(out[0] == 0.0f, "a new cycle's input replaces the old (silence in, silence out)");
    printf(fails ? "FAILED\n" : "ALL PASSED\n");
    return fails != 0;
}
