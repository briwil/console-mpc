/*
 * mapping.h - MPC Sample controls <-> Ableton Move controls (pure logic, no hardware calls).
 *
 * Console was written for the Move. Instead of rewriting it, the bridge makes the MPC "look like" a Move:
 *   MPC -> Console:  MPC pads / buttons / knobs become the Move's channel-16 MIDI (see MOVE-NOTES.md).
 *   Console -> MPC:  Move pad / button lights become MPC pad (SysEx RGB) and button (CC) lights.
 *
 * EVERYTHING in the tables below is a FIRST GUESS to be tried on the device and changed freely.
 * Layout summary:
 *   Pads 1-16      the left 4x4 of the Move's pads (the drums). PAD BANK toggles to the right 4x4.
 *   SEQ button     toggles "step mode": the 16 pads become the Move's 16 step buttons.
 *   KNOB FX        latches KNOB MODE: pads 1-8 become Move knobs 1-8 (hold a pad, turn the encoder; pads 9-16 are silent).
 *                  Without a pad held the encoder is the jog wheel. K1-K3 are always Move knobs 1-3.  FADER = Move knob 8.
 *   MAIN VOLUME    = Move volume knob.   Encoder = jog wheel (push = jog press).
 */
#ifndef MAPPING_H
#define MAPPING_H

#include <stdint.h>

/* ---- what mapping.h needs from its host (the bridge, or a test) ---- */
/* send one message (1-3 bytes) to Console as if the Move sent it */
static void to_console(const uint8_t *m, int n);
/* set an MPC pad light (0-15, 0-127 per channel) / an MPC button light (note number, on/off) */
static void mpc_pad_light(int pad, int r, int g, int b);
static void mpc_btn_light(int note, int on);

/* ---- button table: MPC button note -> Move button CC ---- */
struct bmap { uint8_t mpc, move; };
static const struct bmap BUTTONS[] = {
    { 0x31, 49 },   /* SHIFT          -> Shift   */
    { 0x52, 85 },   /* PLAY           -> Play    */
    { 0x50, 86 },   /* SEQ RECORD     -> Record  */
    { 0x49, 118 },  /* SAMPLE RECORD  -> Sample  */
    { 0x51, 51 },   /* STOP           -> Back    (Shift + Back quits Console) */
    { 0x09, 119 },  /* ERASE          -> Delete  */
    { 0x2B, 88 },   /* MUTE           -> Mute    */
    { 0x35, 60 },   /* TAP TEMPO      -> Copy    */
    { 0x0B, 56 },   /* NOTE REPEAT    -> Undo    */
    { 0x4B, 58 },   /* CHOP           -> Loop    */
    { 0x28, 52 },   /* 16 LEVELS      -> Capture */
    { 0x36, 55 },   /* PLUS           -> + (octave up)   */
    { 0x37, 54 },   /* MINUS          -> - (octave down) */
    { 0x0C, 43 },   /* B1  -> left button 1 (top)    */
    { 0x0D, 42 },   /* B2  -> left button 2          */
    { 0x0E, 41 },   /* B3  -> left button 3          */
    { 0x01, 40 },   /* PAD FX -> left button 4 (bottom) */
    { 0x24, 50 },   /* SAMPLE SELECT  -> Menu (Shift + Menu: export) */
    { 0x06, 62 },   /* button 0x06 (name on the panel unknown) -> left arrow, a guess */
    { 0x4A, 63 },   /* (unmatched MPC button, guess) -> right arrow */
};
#define NBUTTONS ((int)(sizeof BUTTONS / sizeof BUTTONS[0]))

/* buttons the bridge keeps for itself */
#define MPC_SEQ      0x07   /* step mode on / off */
#define MPC_PADBANK  0x23   /* left / right 4x4 */
#define MPC_KNOBFX   0x00   /* knob bank */
#define MPC_ENC_PUSH 0x6F

static const uint8_t MPC_PADNOTE[16] = { 37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53 };

/* ---- state ---- */
static int step_mode, right_bank, knob_mode;
static int pad_knob[16];                    /* knob mode: which Move knob (0-7) each held pad is touching, -1 none */
static int knob_stamp[16], knob_clock;      /* ... and the order they were pressed (the last one wins) */
static int shift_held, stop_target = -1;     /* STOP: stops playback (Play) while playing, else Back; Shift + STOP = Back */
static int pad_target[16];                  /* Move note each MPC pad is holding down (-1 none) */
static int knob_last[5] = { -1, -1, -1, -1, -1 };   /* K1 K2 K3 VOL FADER */
static uint8_t move_pad[32];                /* Console's colour (velocity) for each Move pad, row*8+col */
static uint8_t move_step[16];               /* ... and for each step button */
static uint8_t move_btn[128];               /* ... and button lights by Move CC */
static int shown_rgb[16] = { -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1 };
static int shown_btn[128];                  /* 0 = unknown, 1 = off, 2 = on */

/* ---- colours: Move light velocity -> MPC RGB (0-127). First guess; Console uses 120 white, 127 red, 22 purple ---- */
static void colour_rgb(int v, int *r, int *g, int *b)
{
    if (v <= 0) { *r = *g = *b = 0; return; }
    if (v == 120) { *r = *g = *b = 100; return; }                 /* white */
    if (v == 127) { *r = 127; *g = 0; *b = 0; return; }           /* red */
    if (v == 118) { *r = *g = *b = 40; return; }                  /* light grey */
    /* the rest: walk round the colour wheel so different numbers look different */
    int h = (v * 37) % 360, s = h / 60, f = (h % 60) * 127 / 60;
    switch (s) {
    case 0: *r = 127; *g = f; *b = 0; break;
    case 1: *r = 127 - f; *g = 127; *b = 0; break;
    case 2: *r = 0; *g = 127; *b = f; break;
    case 3: *r = 0; *g = 127 - f; *b = 127; break;
    case 4: *r = f; *g = 0; *b = 127; break;
    default: *r = 127; *g = 0; *b = 127 - f; break;
    }
    *r = *r * 3 / 4; *g = *g * 3 / 4; *b = *b * 3 / 4;
}

/* ---- lights: work out what each MPC pad should show and send what changed ---- */
static void refresh_pads(void)
{
    for (int i = 0; i < 16; i++) {
        int v = step_mode ? move_step[i] : move_pad[(i / 4) * 8 + (i % 4) + (right_bank ? 4 : 0)];
        int r, g, b;
        colour_rgb(v, &r, &g, &b);
        if (v == 0) { r = 0; g = 6; b = 14; }                       /* idle: a faint blue so the pads can be found */
        if (knob_mode) {                                            /* pads 1-8 = knobs 1-8; the touched one is bright */
            if (i < 8) { if (pad_knob[i] >= 0) { r = 30; g = 127; b = 110; } else { r = 0; g = 40; b = 48; } }
            else { r = 0; g = 1; b = 2; }
        }
        int key = (r << 16) | (g << 8) | b;
        if (shown_rgb[i] != key) { shown_rgb[i] = key; mpc_pad_light(i, r, g, b); }
    }
}

static void set_btn_light(int note, int on)
{
    if (note < 0 || note > 127) return;
    if (shown_btn[note] != on + 1) { shown_btn[note] = on + 1; mpc_btn_light(note, on); }
}

static void refresh_buttons(void)
{
    for (int i = 0; i < NBUTTONS; i++) set_btn_light(BUTTONS[i].mpc, move_btn[BUTTONS[i].move] ? 1 : 0);
    set_btn_light(MPC_SEQ, step_mode);
    set_btn_light(MPC_PADBANK, right_bank);
    set_btn_light(MPC_KNOBFX, knob_mode);
}

static void mapping_init(void)
{
    for (int i = 0; i < 16; i++) { pad_target[i] = -1; pad_knob[i] = -1; }
    refresh_pads();
    refresh_buttons();
}

/* ---- Console -> MPC: a message from Console's light port ---- */
static void lights_from_console(const uint8_t *m, int n)
{
    if (n < 3) return;
    int st = m[0] & 0xF0, d1 = m[1] & 127, d2 = m[2] & 127;
    if ((m[0] & 0x0F) != 15) return;                               /* the Move's channel 16 only */
    if (st == 0x80) { st = 0x90; d2 = 0; }
    if (st == 0x90) {
        if (d1 >= 68 && d1 <= 99) { move_pad[d1 - 68] = (uint8_t)d2; refresh_pads(); }
        else if (d1 >= 16 && d1 <= 31) { move_step[d1 - 16] = (uint8_t)d2; refresh_pads(); }
    } else if (st == 0xB0) {
        if (d1 >= 16 && d1 <= 31) return;                          /* the printed step icons: no MPC equivalent */
        move_btn[d1] = (uint8_t)d2;
        refresh_buttons();
    }
}

/* ---- MPC -> Console ---- */
static void send3(int st, int a, int b)
{
    uint8_t m[3] = { (uint8_t)st, (uint8_t)a, (uint8_t)b };
    to_console(m, 3);
}

#ifndef KNOB_STEP
#define KNOB_STEP 4
#endif

/* an absolute knob (0-127) becomes "clicks": CC value 1 = one click right, 127 = one click left */
static void knob_clicks(int slot, int val, int move_cc)
{
    if (knob_last[slot] < 0) { knob_last[slot] = val; return; }
    int d = val - knob_last[slot];
    knob_last[slot] = val;
    if (d == 0) return;
    int n = d < 0 ? -d : d;
    if (n > 8) n = 8;
    for (int i = 0; i < n; i++) send3(0xBF, move_cc, d > 0 ? 1 : 127);
}

/* the knob a held pad is touching (the pad pressed last), or -1 */
static int held_knob(void)
{
    int best = -1, k = -1;
    for (int i = 0; i < 16; i++)
        if (pad_knob[i] >= 0 && knob_stamp[i] > best) { best = knob_stamp[i]; k = pad_knob[i]; }
    return k;
}

static void release_knob_pads(void)
{
    for (int i = 0; i < 16; i++)
        if (pad_knob[i] >= 0) { send3(0x8F, pad_knob[i], 0); pad_knob[i] = -1; }
}

static void mpc_pad_event(int idx, int vel, int on)
{
    if (idx < 0 || idx > 15) return;
    if (on && knob_mode) {
        if (idx < 8) {
            pad_knob[idx] = idx;
            knob_stamp[idx] = ++knob_clock;
            send3(0x9F, idx, 127);                      /* "knob touched": Console shows the value */
            refresh_pads();
        }
        return;                                         /* pads 9-16: silent */
    }
    if (!on && pad_knob[idx] >= 0) {
        send3(0x8F, pad_knob[idx], 0);                  /* touch ends */
        pad_knob[idx] = -1;
        refresh_pads();
        return;
    }
    if (on) {
        int note = step_mode ? 16 + idx : 68 + (idx / 4) * 8 + (idx % 4) + (right_bank ? 4 : 0);
        pad_target[idx] = note;
        send3(0x9F, note, vel > 0 ? vel : 100);
    } else if (pad_target[idx] >= 0) {
        send3(0x8F, pad_target[idx], 0);
        pad_target[idx] = -1;
    }
}

#define MPC_SHIFT 0x31
#define MPC_STOP  0x51
static void mpc_button_event(int note, int down)
{
    if (note == MPC_SHIFT) shift_held = down;
    if (note == MPC_STOP) {
        if (down) stop_target = (!shift_held && move_btn[85]) ? 85 : 51;   /* move_btn[85]: Console's Play light = playing */
        if (stop_target >= 0) send3(0xBF, stop_target, down ? 127 : 0);
        if (!down) stop_target = -1;
        return;
    }
    if (note == MPC_ENC_PUSH) { send3(0xBF, 3, down ? 127 : 0); return; }
    if (down && note == MPC_SEQ) { step_mode = !step_mode; refresh_pads(); refresh_buttons(); return; }
    if (down && note == MPC_PADBANK) { right_bank = !right_bank; refresh_pads(); refresh_buttons(); return; }
    if (down && note == MPC_KNOBFX) { release_knob_pads(); knob_mode = !knob_mode; refresh_pads(); refresh_buttons(); return; }
    if (note == MPC_SEQ || note == MPC_PADBANK || note == MPC_KNOBFX) return;
    for (int i = 0; i < NBUTTONS; i++)
        if (BUTTONS[i].mpc == note) { send3(0xBF, BUTTONS[i].move, down ? 127 : 0); return; }
}

static void mpc_cc_event(int cc, int val)
{
    switch (cc) {
    case 0x10: case 0x11: case 0x12:                      /* K1-K3 = Move knobs 1-3 */
        knob_clicks(cc - 0x10, val, 71 + (cc - 0x10));
        break;
    case 0x13: knob_clicks(3, val, 79); break;            /* MAIN VOLUME -> volume knob */
    case 0x14: knob_clicks(4, val, 78); break;            /* FADER -> knob 8 */
    case 0x64: {                                          /* encoder: relative already */
        int k = held_knob();                              /* a knob-mode pad held: that knob; else the jog wheel */
        for (int i = 0; i < (k >= 0 ? KNOB_STEP : 1); i++)   /* the MPC encoder is slow next to a Move knob: several clicks per notch */
            send3(0xBF, k >= 0 ? 71 + k : 14, val == 0x7F ? 127 : 1);
        break;
    }
    }
}

/* ---- the MPC's raw serial-MIDI bytes -> events (running status; SysEx and real-time skipped) ---- */
static void mpc_midi_byte(uint8_t b)
{
    static uint8_t st, d[2];
    static int n, insx;
    if (b >= 0xF8) return;
    if (b == 0xF0) { insx = 1; return; }
    if (b == 0xF7) { insx = 0; return; }
    if (b & 0x80) { insx = 0; st = b; n = 0; return; }
    if (insx || !st) return;
    d[n++] = b;
    int need = ((st & 0xF0) == 0xC0 || (st & 0xF0) == 0xD0) ? 1 : 2;
    if (n < need) return;
    n = 0;
    int ch = st & 15, k = st & 0xF0;
    if (ch == 9) {                                                  /* channel 10: pads */
        int idx = -1;
        for (int i = 0; i < 16; i++) if (MPC_PADNOTE[i] == d[0]) idx = i;
        if (idx >= 0) {
            if (k == 0x90 && d[1] > 0) mpc_pad_event(idx, d[1], 1);
            else if (k == 0x80 || (k == 0x90 && d[1] == 0)) mpc_pad_event(idx, 0, 0);
        }
    } else if (ch == 0) {                                           /* channel 1: buttons, knobs */
        if (k == 0x90 && d[1] > 0) mpc_button_event(d[0], 1);
        else if (k == 0x80 || (k == 0x90 && d[1] == 0)) mpc_button_event(d[0], 0);
        else if (k == 0xB0) mpc_cc_event(d[0], d[1]);
    }
}

#endif
