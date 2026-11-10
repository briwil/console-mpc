/*
 * demo.c - end-to-end check of the bridge on the MPC, without Python.
 *
 * Loads Console's real sound core (libconsolecore.so, built for the Move) on top of libjack_mpc.so and uses the
 * core's own control / light / screen calls, exactly as Console's Python would. Press things on the MPC:
 * the screen shows what Console would receive (as Move controls), pads and buttons light up while held.
 *
 *   ./bridge_demo /path/to/libjack_mpc.so /path/to/libconsolecore.so [seconds]
 *
 * It stops the stock MPC app first and starts it again at the end (also on Ctrl-C).
 * Built like the other tools (see build.sh -> demo target). Host test: -DHOST_TEST.
 */
#include <stdint.h>
#include <stddef.h>
#ifdef HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <unistd.h>
#include <signal.h>
#else
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern int usleep(unsigned);
extern int system(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern int atoi(const char *);
extern void *memset(void *, int, unsigned long);
extern void *memcpy(void *, const void *, unsigned long);
extern int puts(const char *);
typedef void (*sighandler_t)(int);
extern sighandler_t signal(int, sighandler_t);
__asm__(".text\n.globl _start\n.type _start,%function\n_start:\n"
        "  mov x29, #0\n  mov x30, #0\n  mov x5, x0\n  ldr x1, [sp]\n  add x2, sp, #8\n  mov x6, sp\n"
        "  adrp x0, main\n  add x0, x0, :lo12:main\n  mov x3, #0\n  mov x4, #0\n"
        "  bl __libc_start_main\n  brk #0\n");
#endif
#include "font5x7.h"

static volatile int quit;
static void on_sig(int s) { (void)s; quit = 1; }

static uint8_t frame[1032];
static void px(int x, int y)
{
    if (x < 0 || x > 127 || y < 0 || y > 63) return;
    frame[8 + (y / 8) * 128 + x] |= (uint8_t)(1 << (y & 7));
}
static void text(int x, int y, const char *s)
{
    for (; *s; s++, x += 6) {
        const unsigned char *g = FONT[(unsigned char)*s & 127];
        for (int c = 0; c < 5; c++)
            for (int r = 0; r < 7; r++)
                if (g[c] & (1 << r)) px(x + c, y + r);
    }
}

int main(int argc, char **argv)
{
    if (argc < 3) { puts("usage: bridge_demo libjack_mpc.so libconsolecore.so [seconds]"); return 2; }
    int secs = argc > 3 ? atoi(argv[3]) : 60;
    signal(2, on_sig);
    signal(15, on_sig);
#ifndef HOST_TEST
    system("systemctl unset-environment LD_PRELOAD; systemctl stop ac50.service");
    usleep(1500000);
#endif
    void *core = dlopen(argv[2], 2 /*RTLD_NOW*/ | 0x100 /*RTLD_GLOBAL*/);
    if (!core) { puts("cannot load the core"); goto out; }
    int (*core_open)(const char *, const char *) = dlsym(core, "core_open");
    void (*core_close)(void) = dlsym(core, "core_close");
    int (*core_read_midi)(uint8_t *, int) = dlsym(core, "core_read_midi");
    int (*core_send_midi)(const uint8_t *, int) = dlsym(core, "core_send_midi");
    void (*core_set_display)(const uint8_t *) = dlsym(core, "core_set_display");
    if (!core_open || !core_read_midi || !core_send_midi || !core_set_display) { puts("core functions missing"); goto out; }
    int r = core_open(argv[1], "console");
    if (r != 0) { char m[64]; snprintf(m, sizeof m, "core_open failed: %d", r); puts(m); goto out; }
    puts("running: press pads / buttons, turn knobs. Ctrl-C to stop.");

    char last[40] = "(nothing yet)", lastb[40] = "", l3[40];
    int knob[8] = { 0 }, vol = 0, jog = 0, events = 0;
    for (int t = 0; t < secs * 50 && !quit; t++) {
        uint8_t buf[12 * 64];
#ifdef HOST_TEST
        if (t == 10) {
            void (*inj)(const unsigned char *, int) = dlsym(RTLD_DEFAULT, "mpcshim_test_inject");
            static const unsigned char pad[] = { 0x99, 37, 90, 0x90, 0x52, 0x7F, 0xB0, 0x10, 10, 0xB0, 0x10, 13 };
            if (inj) inj(pad, sizeof pad);
        }
#endif
        int k = core_read_midi(buf, 64);
        for (int i = 0; i < k; i++) {
            const uint8_t *b = buf + 12 * i + 8;
            int st = b[0] & 0xF0, d1 = b[1], d2 = b[2];
            events++;
            if (st == 0x90 || st == 0x80) {
                int on = st == 0x90 && d2 > 0;
                if (d1 >= 68 && d1 <= 99)
                    snprintf(last, sizeof last, "PAD %d,%d %s %d", (d1 - 68) / 8, (d1 - 68) % 8, on ? "ON" : "OFF", d2);
                else
                    snprintf(last, sizeof last, "NOTE %d %s %d", d1, on ? "ON" : "OFF", d2);
                uint8_t lm[3] = { 0x9F, (uint8_t)d1, (uint8_t)(on ? 120 : 0) };
                core_send_midi(lm, 3);
            } else if (st == 0xB0) {
                if (d1 >= 71 && d1 <= 78) { knob[d1 - 71] += d2 == 1 ? 1 : -1; snprintf(last, sizeof last, "KNOB %d", d1 - 70); }
                else if (d1 == 79) { vol += d2 == 1 ? 1 : -1; snprintf(last, sizeof last, "VOLUME"); }
                else if (d1 == 14) { jog += d2 == 1 ? 1 : -1; snprintf(last, sizeof last, "JOG"); }
                else {
                    snprintf(last, sizeof last, "BUTTON CC %d %s", d1, d2 ? "DOWN" : "UP");
                    snprintf(lastb, sizeof lastb, "last button: %d", d1);
                    uint8_t lm[3] = { 0xBF, (uint8_t)d1, (uint8_t)(d2 ? 127 : 0) };
                    core_send_midi(lm, 3);
                }
            }
        }
        if (k || t % 25 == 0) {
            memset(frame, 0, sizeof frame);
            memcpy(frame, "MOVEDISP", 8);
            text(0, 0, "MPC AS A MOVE");
            text(0, 12, last);
            snprintf(l3, sizeof l3, "K %d %d %d %d", knob[0], knob[1], knob[2], knob[3]);
            text(0, 24, l3);
            snprintf(l3, sizeof l3, "K %d %d %d %d", knob[4], knob[5], knob[6], knob[7]);
            text(0, 33, l3);
            snprintf(l3, sizeof l3, "VOL %d JOG %d", vol, jog);
            text(0, 44, l3);
            snprintf(l3, sizeof l3, "EVENTS %d", events);
            text(0, 55, l3);
            core_set_display(frame);
        }
        usleep(20000);
    }
#ifdef HOST_TEST
    printf("last=%s events=%d knob1=%d\n", last, events, knob[0]);
#endif
    if (core_close) core_close();
out:
#ifndef HOST_TEST
    system("systemctl start ac50.service");
#endif
    return 0;
}
