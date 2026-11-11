/*
 * shim_test.c - host test for the bridge (fake hardware). Run through bridge/test/run.sh.
 *
 * A: a stand-in "core" drives the shim through the same JACK calls Console's core makes. Checks MPC input ->
 *    Move messages, Move lights -> MPC lights, the screen, and the audio loop.
 * B: Console's real core (libconsolecore) is opened on the shim, must report success, and then runs for a while.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct { uint32_t time; size_t size; unsigned char *buffer; } jack_midi_event_t;
typedef int (*JackProcess)(uint32_t, void *);

static void *lib;
#define FN(ret, name, args) static ret (*name) args
FN(void *, c_open, (const char *, int, int *, ...));
FN(void *, c_port, (void *, const char *, const char *, unsigned long, unsigned long));
FN(void *, c_buf, (void *, uint32_t));
FN(int, c_cb, (void *, JackProcess, void *));
FN(int, c_activate, (void *));
FN(int, c_deactivate, (void *));
FN(uint32_t, m_count, (void *));
FN(int, m_get, (jack_midi_event_t *, void *, uint32_t));
FN(void, m_clear, (void *));
FN(int, m_write, (void *, uint32_t, const unsigned char *, size_t));
static void (*inject)(const unsigned char *, int);
static void (*set_log)(FILE *);
static uint32_t *screen;
static long *frames;

static int failures;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); failures++; } else printf("ok:   %s\n", msg); } while (0)

static void *cl, *p_ol, *p_or, *p_cin, *p_lights, *p_disp;
static unsigned char got[256][3];
static volatile int ngot;
static volatile int sent_lights;
static unsigned char lightmsgs[4][3] = { { 0x9F, 68, 127 }, { 0x9F, 69, 120 }, { 0xBF, 85, 127 }, { 0x9F, 16, 120 } };

static int fake_process(uint32_t n, void *arg)
{
    (void)arg;
    float *l = c_buf(p_ol, n), *r = c_buf(p_or, n);
    static float ph;
    for (uint32_t i = 0; i < n; i++) { l[i] = r[i] = 0.2f * (ph < 0.5f ? 1 : -1); ph += 440.f / 44100.f; if (ph >= 1) ph -= 1; }
    void *cin = c_buf(p_cin, n);
    uint32_t k = m_count(cin);
    for (uint32_t i = 0; i < k; i++) {
        jack_midi_event_t ev;
        if (m_get(&ev, cin, i) == 0 && ev.size == 3 && ngot < 256) {
            memcpy(got[ngot], ev.buffer, 3);
            ngot++;
        }
    }
    void *lo = c_buf(p_lights, n), *dd = c_buf(p_disp, n);
    m_clear(lo);
    m_clear(dd);
    if (sent_lights == 1) {
        for (int i = 0; i < 4; i++) m_write(lo, 0, lightmsgs[i], 3);
        unsigned char d[1032];
        memset(d, 0, sizeof d);
        memcpy(d, "MOVEDISP", 8);
        d[8 + 0] = 0x01;                      /* pixel (0,0) on */
        d[8 + 128 * 7 + 127] = 0x80;          /* pixel (127,63) on */
        m_write(dd, 0, d, 1032);
        sent_lights = 2;
    }
    return 0;
}

static void send(const unsigned char *b, int n) { inject(b, n); usleep(30000); }

static int expect(int idx, int a, int b, int c)
{
    return idx < ngot && got[idx][0] == a && got[idx][1] == b && got[idx][2] == c;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: shim_test libjack_mpc_host.so libconsolecore_host.so\n"); return 2; }
    lib = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (!lib) { printf("dlopen: %s\n", dlerror()); return 2; }
#define G(v, n) *(void **)&v = dlsym(lib, n); if (!v) { printf("missing %s\n", n); return 2; }
    G(c_open, "jack_client_open"); G(c_port, "jack_port_register"); G(c_buf, "jack_port_get_buffer");
    G(c_cb, "jack_set_process_callback"); G(c_activate, "jack_activate"); G(c_deactivate, "jack_deactivate");
    G(m_count, "jack_midi_get_event_count"); G(m_get, "jack_midi_event_get"); G(m_clear, "jack_midi_clear_buffer");
    G(m_write, "jack_midi_event_write"); G(inject, "mpcshim_test_inject"); G(set_log, "mpcshim_test_log");
    screen = dlsym(lib, "mpcshim_test_screen"); frames = dlsym(lib, "mpcshim_test_frames");
    FILE *lg = fopen("/tmp/shim_test_leds.txt", "w");
    set_log(lg);

    int st;
    cl = c_open("t", 1, &st);
    p_ol = c_port(cl, "out_L", "32 bit float mono audio", 2, 0);
    p_or = c_port(cl, "out_R", "32 bit float mono audio", 2, 0);
    c_port(cl, "in_L", "32 bit float mono audio", 1, 0);
    c_port(cl, "in_R", "32 bit float mono audio", 1, 0);
    p_cin = c_port(cl, "controls_in", "8 bit raw midi", 1, 0);
    p_lights = c_port(cl, "lights_out", "8 bit raw midi", 2, 0);
    p_disp = c_port(cl, "display_out", "8 bit raw midi", 2, 0);
    c_cb(cl, fake_process, 0);
    CHECK(c_activate(cl) == 0, "A: activate");
    usleep(100000);
    CHECK(*frames > 1000, "A: audio loop is running");

#ifdef RETRIG_TEST
    {   /* the drum repeat in knob mode: only while a pad is held and the encoder is turning */
        send((unsigned char[]){ 0x99, 37, 90 }, 3);
        send((unsigned char[]){ 0x89, 37, 0 }, 3);                    /* last drum = note 68 */
        send((unsigned char[]){ 0x90, 0x00, 0x7F }, 3);
        send((unsigned char[]){ 0x80, 0x00, 0x00 }, 3);               /* knob mode on */
        send((unsigned char[]){ 0x99, 42, 80 }, 3);                   /* hold pad 3 */
        int before = ngot;
        for (int i = 0; i < 10; i++) { send((unsigned char[]){ 0xB0, 0x64, 0x01 }, 3); usleep(170000); }
        CHECK(ngot - before >= 10, "R: turning in knob mode repeats the last drum about every 0.4 s");
        usleep(1200000);
        int after = ngot;
        usleep(1000000);
        CHECK(ngot == after, "R: no repeats once the encoder stops");
        int hits = 0, offs = 0;
        for (int i = before; i < ngot; i++) if (got[i][0] == 0x9F && got[i][1] == 68 && got[i][2] == 100) hits++;
        for (int i = before; i < ngot; i++) if (got[i][0] == 0x8F && got[i][1] == 68) offs++;
        CHECK(hits >= 3 && hits <= 7 && offs == hits, "R: 3-7 repeats, and every repeat gets its note-off");
        printf(failures ? "FAILED\n" : "ALL PASSED\n");
        return failures ? 1 : 0;
    }
#endif
    /* pad 1 (bottom left) down / up -> Move pad note 68 */
    send((unsigned char[]){ 0x99, 37, 90 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    CHECK(expect(0, 0x9F, 68, 90) && expect(1, 0x8F, 68, 0), "A: pad 1 -> Move note 68 on/off");
    /* pad 16 (top right of the left half) -> row 3, col 3 = 68 + 24 + 3 = 95 */
    send((unsigned char[]){ 0x99, 53, 100 }, 3);
    send((unsigned char[]){ 0x89, 53, 0 }, 3);
    CHECK(expect(2, 0x9F, 95, 100) && expect(3, 0x8F, 95, 0), "A: pad 16 -> Move note 95");
    /* PLAY button */
    send((unsigned char[]){ 0x90, 0x52, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x52, 0x00 }, 3);
    CHECK(expect(4, 0xBF, 85, 127) && expect(5, 0xBF, 85, 0), "A: PLAY -> Move Play (CC 85)");
    /* K1: first value only primes; then +5 = five clicks right */
    send((unsigned char[]){ 0xB0, 0x10, 20 }, 3);
    send((unsigned char[]){ 0xB0, 0x10, 25 }, 3);
    CHECK(ngot == 6 + 5 && expect(6, 0xBF, 71, 1) && expect(10, 0xBF, 71, 1), "A: K1 +5 -> 5 clicks right on knob 1");
    send((unsigned char[]){ 0xB0, 0x10, 23 }, 3);
    CHECK(ngot == 13 && expect(11, 0xBF, 71, 127), "A: K1 -2 -> 2 clicks left");
    /* encoder */
    send((unsigned char[]){ 0xB0, 0x64, 0x7F }, 3);
    CHECK(expect(13, 0xBF, 14, 127), "A: encoder down -> jog wheel left");
    /* KNOB FX latches knob mode: pads 1-8 = knobs 1-8 (touch + encoder), pads 9-16 silent, no pad held = jog */
    send((unsigned char[]){ 0x90, 0x00, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x00, 0x00 }, 3);
    send((unsigned char[]){ 0x99, 42, 80 }, 3);                       /* pad 3 down */
    send((unsigned char[]){ 0xB0, 0x64, 0x01 }, 3);
    send((unsigned char[]){ 0xB0, 0x64, 0x7F }, 3);
    send((unsigned char[]){ 0x89, 42, 0 }, 3);
    CHECK(expect(14, 0x9F, 2, 127) && expect(15, 0xBF, 73, 1) && expect(16, 0xBF, 73, 127) && expect(17, 0x8F, 2, 0),
          "A: knob mode: hold pad 3 -> touch knob 3, encoder turns Move knob 3 (CC 73), release ends the touch");
    send((unsigned char[]){ 0x99, 47, 80 }, 3);                       /* pad 10: silent */
    send((unsigned char[]){ 0x89, 47, 0 }, 3);
    send((unsigned char[]){ 0xB0, 0x64, 0x01 }, 3);                   /* no pad held: jog wheel */
    CHECK(ngot == 19 && expect(18, 0xBF, 14, 1), "A: knob mode: pad 10 silent; encoder alone = jog wheel");
    send((unsigned char[]){ 0x99, 37, 80 }, 3);                       /* pad 1 held, then KNOB FX off: touch ends */
    send((unsigned char[]){ 0x90, 0x00, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x00, 0x00 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    CHECK(expect(19, 0x9F, 0, 127) && expect(20, 0x8F, 0, 0) && ngot == 21, "A: leaving knob mode ends a touch; no stray pad note-off");
    send((unsigned char[]){ 0xB0, 0x10, 24 }, 3);                     /* K1: 23 -> 24 = one click right on knob 1 */
    CHECK(expect(21, 0xBF, 71, 1) && ngot == 22, "A: K1 is always Move knob 1");
    /* SEQ: step mode; pad 5 -> step 20 (note 16 + 4) */
    send((unsigned char[]){ 0x90, 0x07, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x07, 0x00 }, 3);
    send((unsigned char[]){ 0x99, 40, 80 }, 3);
    send((unsigned char[]){ 0x89, 40, 0 }, 3);
    CHECK(expect(22, 0x9F, 20, 80) && expect(23, 0x8F, 20, 0), "A: step mode: pad 5 -> step button 5 (note 20)");
    /* SEQ again, PAD BANK: pad 1 -> right half, note 72 */
    send((unsigned char[]){ 0x90, 0x07, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x07, 0x00 }, 3);
    send((unsigned char[]){ 0x90, 0x23, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x23, 0x00 }, 3);
    send((unsigned char[]){ 0x99, 37, 70 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    CHECK(expect(24, 0x9F, 72, 70) && expect(25, 0x8F, 72, 0), "A: PAD BANK: pad 1 -> right half (note 72)");
    /* released after a mode change still releases the right note */
    send((unsigned char[]){ 0x99, 37, 70 }, 3);
    send((unsigned char[]){ 0x90, 0x23, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x23, 0x00 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    CHECK(expect(26, 0x9F, 72, 70) && expect(27, 0x8F, 72, 0), "A: note-off matches note-on after a bank change");
    {   /* MAIN VOLUME is absolute: the first move syncs (50 down), then up to the knob's place; later moves are the difference */
        int b = ngot, down = 0, up = 0;
        send((unsigned char[]){ 0xB0, 0x13, 127 }, 3);
        for (int i = b; i < ngot; i++) { if (got[i][1] == 79 && got[i][2] == 127) down++; if (got[i][1] == 79 && got[i][2] == 1) up++; }
        CHECK(down == 50 && up == 50, "A: MAIN VOLUME first move: 50 down, then 50 up (full)");
        b = ngot; down = up = 0;
        send((unsigned char[]){ 0xB0, 0x13, 64 }, 3);                  /* halfway: 25 down from 50 */
        for (int i = b; i < ngot; i++) { if (got[i][1] == 79 && got[i][2] == 127) down++; if (got[i][1] == 79 && got[i][2] == 1) up++; }
        CHECK(down == 25 && up == 0, "A: MAIN VOLUME to half: 25 clicks down");
        b = ngot;
        send((unsigned char[]){ 0xB0, 0x14, 10 }, 3);
        send((unsigned char[]){ 0xB0, 0x14, 12 }, 3);
        CHECK(ngot == b + 2 && got[b][1] == 74 && got[b + 1][1] == 74, "A: FADER = knob 4 (CC 74)");
    }
    {   /* PLUS / MINUS = arrows; Shift + them = Move + / - (Console sees Shift released meanwhile); LOOP = Loop */
        int b = ngot;
        send((unsigned char[]){ 0x90, 0x36, 0x7F }, 3);
        send((unsigned char[]){ 0x80, 0x36, 0x00 }, 3);
        send((unsigned char[]){ 0x90, 0x37, 0x7F }, 3);
        send((unsigned char[]){ 0x80, 0x37, 0x00 }, 3);
        CHECK(expect(b, 0xBF, 63, 127) && expect(b + 2, 0xBF, 62, 127), "A: PLUS = right arrow, MINUS = left arrow");
        b = ngot;
        send((unsigned char[]){ 0x90, 0x31, 0x7F }, 3);
        send((unsigned char[]){ 0x90, 0x36, 0x7F }, 3);
        send((unsigned char[]){ 0x80, 0x36, 0x00 }, 3);
        send((unsigned char[]){ 0x80, 0x31, 0x00 }, 3);
        CHECK(expect(b, 0xBF, 49, 127) && expect(b + 1, 0xBF, 49, 0) && expect(b + 2, 0xBF, 55, 127) && expect(b + 3, 0xBF, 49, 127),
              "A: Shift + PLUS = Move + (Shift lifted for it, then back)");
        b = ngot;
        send((unsigned char[]){ 0x90, 0x4A, 0x7F }, 3);
        send((unsigned char[]){ 0x80, 0x4A, 0x00 }, 3);
        CHECK(expect(b, 0xBF, 58, 127), "A: LOOP -> Move Loop");
    }
    {   /* the tape page (Console writes T to /tmp/console-pagemode): pads are the step buttons there */
        int b = ngot;
        FILE *pf = fopen("/tmp/console-pagemode", "wb"); fputc('T', pf); fclose(pf);
        usleep(200000);
        send((unsigned char[]){ 0x99, 37, 70 }, 3);
        send((unsigned char[]){ 0x89, 37, 0 }, 3);
        send((unsigned char[]){ 0x90, 0x31, 0x7F }, 3);
        send((unsigned char[]){ 0x99, 36, 71 }, 3);                   /* Shift + pad 2: Shift + step 2, not a pattern pad */
        send((unsigned char[]){ 0x89, 36, 0 }, 3);
        send((unsigned char[]){ 0x80, 0x31, 0x00 }, 3);
        CHECK(expect(b, 0x9F, 16, 70) && expect(b + 2, 0xBF, 49, 127) && expect(b + 3, 0x9F, 17, 71), "A: tape page: pads are the step buttons (also with Shift)");
        pf = fopen("/tmp/console-pagemode", "wb"); fputc('O', pf); fclose(pf);
        usleep(200000);
        b = ngot;
        send((unsigned char[]){ 0x99, 37, 70 }, 3);
        send((unsigned char[]){ 0x89, 37, 0 }, 3);
        CHECK(expect(b, 0x9F, 68, 70), "A: other pages: the pads are drum pads again");
        remove("/tmp/console-pagemode");
    }
    int s0 = ngot;
    /* Shift + SEQ: the pads are Move pads 1-32 in order (a step's settings); PAD BANK = 17-32; SEQ goes to steps */
    send((unsigned char[]){ 0x90, 0x31, 0x7F }, 3);
    send((unsigned char[]){ 0x90, 0x07, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x07, 0x00 }, 3);
    send((unsigned char[]){ 0x80, 0x31, 0x00 }, 3);
    send((unsigned char[]){ 0x99, 37, 70 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    send((unsigned char[]){ 0x99, 48, 71 }, 3);                       /* pad 9 */
    send((unsigned char[]){ 0x89, 48, 0 }, 3);
    send((unsigned char[]){ 0x90, 0x23, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x23, 0x00 }, 3);
    send((unsigned char[]){ 0x99, 37, 72 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    send((unsigned char[]){ 0x90, 0x23, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x23, 0x00 }, 3);                   /* bank back */
    CHECK(expect(s0 + 2, 0x9F, 68, 70) && expect(s0 + 4, 0x9F, 76, 71) && expect(s0 + 6, 0x9F, 84, 72), "A: Shift + SEQ: pads = Move pads in order (pad 1 = 68, pad 9 = 76, bank 2: 84)");
    send((unsigned char[]){ 0x90, 0x07, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x07, 0x00 }, 3);                   /* SEQ: back to the steps */
    send((unsigned char[]){ 0x99, 37, 70 }, 3);
    send((unsigned char[]){ 0x89, 37, 0 }, 3);
    CHECK(expect(s0 + 8, 0x9F, 16, 70), "A: SEQ from the settings pads: step mode (pad 1 = step 1)");
    send((unsigned char[]){ 0x90, 0x07, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x07, 0x00 }, 3);                   /* SEQ: normal pads again */

    /* lights and screen */
    sent_lights = 1;
    int g0 = ngot;
    usleep(150000);
    fflush(lg);
    char cmd[256];
    CHECK(sent_lights == 2, "A: core wrote lights and a screen");
    int red = system("grep -q 'MPC<- F0 47 7F 5C 65 00 04 00 7F 00 00 F7' /tmp/shim_test_leds.txt");
    (void)cmd;
    CHECK(red == 0, "A: Move pad 68 colour 127 -> MPC pad 1 red (SysEx)");
    int play = system("grep -q 'MPC<- B0 52 02' /tmp/shim_test_leds.txt");
    CHECK(play == 0, "A: Move Play light -> MPC PLAY button light on");
    int idle = system("grep -q 'MPC<- F0 47 7F 5C 65 00 04 05 00 06 0E F7' /tmp/shim_test_leds.txt");
    CHECK(idle == 0, "A: unlit pads show the faint idle blue");
    CHECK(screen[56 * 320 + 32] == 0x00F2EBDD && screen[(56 + 1) * 320 + 33] == 0x00F2EBDD, "A: screen pixel (0,0) drawn 2x2 at (32,56)");
    CHECK(screen[(56 + 127) * 320 + 32 + 255] == 0x00F2EBDD && screen[56 * 320 + 40] == 0, "A: pixel (127,63) drawn, others dark");
    {   /* a native 320x240 frame from Console takes over the screen; deleting the file gives the Move screen back */
        static unsigned char nat[8 + 320 * 240 * 3];
        memcpy(nat, "CNAT", 4);
        nat[4] = 1;
        nat[8 + (10 * 320 + 20) * 3] = 200; nat[9 + (10 * 320 + 20) * 3] = 100; nat[10 + (10 * 320 + 20) * 3] = 50;
        FILE *nf = fopen("/tmp/console-native.rgb", "wb"); fwrite(nat, 1, sizeof nat, nf); fclose(nf);
        usleep(150000);
        CHECK(screen[10 * 320 + 20] == 0x00C86432 && screen[56 * 320 + 32] == 0, "A: native frame replaces the Move screen (colour kept)");
        nat[4] = 2;
        nat[8 + (11 * 320 + 21) * 3] = 255;
        nf = fopen("/tmp/console-native.rgb.tmp", "wb"); fwrite(nat, 1, sizeof nat, nf); fclose(nf);
        rename("/tmp/console-native.rgb.tmp", "/tmp/console-native.rgb");
        usleep(150000);
        CHECK((screen[11 * 320 + 21] >> 16) == 255, "A: a new counter value shows the new native frame");
        remove("/tmp/console-native.rgb");
        usleep(250000);
        CHECK(screen[10 * 320 + 20] == 0, "A: native file gone -> Move screen again");
    }
    /* STOP: Play is lit (the core said so above) -> STOP presses Play; Shift + STOP = Back */
    send((unsigned char[]){ 0x90, 0x51, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x51, 0x00 }, 3);
    CHECK(expect(g0, 0xBF, 85, 127) && expect(g0 + 1, 0xBF, 85, 0), "A: STOP while playing -> Play (stops it)");
    send((unsigned char[]){ 0x90, 0x31, 0x7F }, 3);
    send((unsigned char[]){ 0x90, 0x51, 0x7F }, 3);
    send((unsigned char[]){ 0x80, 0x51, 0x00 }, 3);
    send((unsigned char[]){ 0x80, 0x31, 0x00 }, 3);
    CHECK(expect(g0 + 2, 0xBF, 49, 127) && expect(g0 + 3, 0xBF, 51, 127) && expect(g0 + 4, 0xBF, 51, 0), "A: Shift + STOP -> Back");
    CHECK(c_deactivate(cl) == 0, "A: deactivate");

    /* B: the real core on the shim */
    void *core = dlopen(argv[2], RTLD_NOW | RTLD_GLOBAL);
    if (!core) { printf("FAIL: B: dlopen core: %s\n", dlerror()); return 1; }
    int (*core_open)(const char *, const char *) = dlsym(core, "core_open");
    void (*core_close)(void) = dlsym(core, "core_close");
    long f0 = *frames;
    int r = core_open(argv[1], "console");
    CHECK(r == 0, "B: the real core_open() succeeds on the shim");
    usleep(500000);
    CHECK(*frames - f0 > 3000, "B: the real core runs on the shim (audio frames flowing)");
    if (core_close) core_close();
    printf("%s (%d failures)\n", failures ? "FAILED" : "ALL PASSED", failures);
    return failures != 0;
}
