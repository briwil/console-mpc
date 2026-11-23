/* rec_test.c - host test for the screen recorder (bridge/screenrec.h): turn it on, show frames, play sound, press pads and
 * buttons, turn it off, then check the files. Run through bridge/test/run.sh (it then runs tools/screenrec-convert.py on them). */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

typedef int (*JackProcess)(uint32_t, void *);
static void *(*c_open)(const char *, int, int *, ...);
static void *(*c_port)(void *, const char *, const char *, unsigned long, unsigned long);
static void *(*c_buf)(void *, uint32_t);
static int (*c_cb)(void *, JackProcess, void *);
static int (*c_activate)(void *), (*c_deactivate)(void *);
static void (*inject)(const unsigned char *, int);
static void *p_ol, *p_or;
static int failures;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL: %s\n", m); failures++; } else printf("ok:   %s\n", m); } while (0)

static int proc(uint32_t n, void *a)
{
    (void)a;
    float *l = c_buf(p_ol, n), *r = c_buf(p_or, n);
    static float ph;
    for (uint32_t i = 0; i < n; i++) { l[i] = r[i] = 0.25f * (ph < 0.5f ? 1 : -1); ph += 440.f / 44100.f; if (ph >= 1) ph -= 1; }
    return 0;
}

static void native(uint32_t seq, uint8_t shade)
{
    static uint8_t b[8 + 320 * 240 * 3];
    memcpy(b, "CNAT", 4); memcpy(b + 4, &seq, 4);
    memset(b + 8, 20, 320 * 240 * 3);
    for (int y = 100; y < 140; y++) for (int x = 10 + seq * 20; x < 60 + seq * 20; x++) { uint8_t *p = b + 8 + (y * 320 + x) * 3; p[0] = shade; p[1] = 200; p[2] = 50; }
    FILE *f = fopen("/tmp/console-native.rgb.new", "wb"); fwrite(b, 1, sizeof b, f); fclose(f);
    rename("/tmp/console-native.rgb.new", "/tmp/console-native.rgb");
}

static long fsize(const char *d, const char *n) { char p[512]; struct stat st; snprintf(p, sizeof p, "%s/%s", d, n); return stat(p, &st) ? -1 : st.st_size; }

int main(int argc, char **argv)
{
    const char *dir = argc > 2 ? argv[2] : "/tmp/rec_test_out";
    void *lib = dlopen(argv[1], RTLD_NOW);
    if (!lib) { printf("dlopen: %s\n", dlerror()); return 2; }
    *(void **)&c_open = dlsym(lib, "jack_client_open"); *(void **)&c_port = dlsym(lib, "jack_port_register");
    *(void **)&c_buf = dlsym(lib, "jack_port_get_buffer"); *(void **)&c_cb = dlsym(lib, "jack_set_process_callback");
    *(void **)&c_activate = dlsym(lib, "jack_activate"); *(void **)&c_deactivate = dlsym(lib, "jack_deactivate");
    *(void **)&inject = dlsym(lib, "mpcshim_test_inject");
    char cmd[600]; snprintf(cmd, sizeof cmd, "rm -rf %s && mkdir -p %s", dir, dir); if (system(cmd)) return 2;
    unlink("/tmp/console-rec"); unlink("/tmp/console-native.rgb");
    void *cl = c_open("t", 0, 0);
    p_ol = c_port(cl, "out_L", "32 bit float mono audio", 2, 0);
    p_or = c_port(cl, "out_R", "32 bit float mono audio", 2, 0);
    c_port(cl, "controls_in", "8 bit raw midi", 1, 0);
    c_port(cl, "lights_out", "8 bit raw midi", 2, 0);
    c_port(cl, "display_out", "8 bit raw midi", 2, 0);
    c_cb(cl, proc, 0);
    if (c_activate(cl)) { printf("activate failed\n"); return 2; }
    native(0, 100);
    usleep(300000);
    FILE *f = fopen("/tmp/console-rec", "w"); fprintf(f, "%s\n", dir); fclose(f);
    usleep(300000);
    native(1, 150);
    const unsigned char pad[] = { 0x99, 37, 100 }, padup[] = { 0x89, 37, 0 }, shift[] = { 0x90, 0x31, 0x7F }, shiftup[] = { 0x80, 0x31, 0 };
    const unsigned char k1[] = { 0xB0, 0x10, 64 }, wheel[] = { 0xB0, 0x64, 0x01 }, wheell[] = { 0xB0, 0x64, 0x7F };
    inject(pad, 3); usleep(200000); inject(padup, 3);
    native(2, 200);
    inject(shift, 3); usleep(100000); inject(shiftup, 3);
    inject(k1, 3); inject(wheel, 3); inject(wheel, 3); inject(wheell, 3);
    usleep(400000);
    native(3, 250);
    usleep(300000);
    unlink("/tmp/console-rec");
    usleep(300000);
    c_deactivate(cl);
    unlink("/tmp/console-native.rgb");
    long v = fsize(dir, "screen.cvr"), a = fsize(dir, "audio.wav"), c = fsize(dir, "controls.txt"), t = fsize(dir, "timing.txt");
    printf("screen %ld  audio %ld  controls %ld  timing %ld\n", v, a, c, t);
    CHECK(v > 8 + 320 * 240 * 3, "screen.cvr has the first frame whole, and more");
    CHECK(v < 8 + 320 * 240 * 3 * 2, "... and only the changes after it");
    CHECK(a > 58 + 44100 * 8 / 2, "audio.wav has about a second of sound");
    CHECK(c > 0, "controls.txt has the panel's messages");
    CHECK(t > 0, "timing.txt is written");
    CHECK(fsize(dir, "lights.txt") > 16 * 10, "lights.txt has every pad's light at the start");
    return failures ? 1 : 0;
}
