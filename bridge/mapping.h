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
    { 0x4B, 118 },  /* CHOP           -> Sample (= SPLICE in Console; Shift: splice all) */
    { 0x51, 51 },   /* STOP           -> Back    (Shift + Back quits Console) */
    { 0x09, 119 },  /* ERASE          -> Delete  */
    { 0x2B, 88 },   /* MUTE           -> Mute    */
    { 0x35, 60 },   /* TAP TEMPO      -> Copy    */
    { 0x0B, 56 },   /* NOTE REPEAT    -> Undo    */
    { 0x4A, 58 },   /* LOOP           -> Loop (the tape's loop in / out) */
    { 0x28, 56 },   /* 16 LEVELS      -> Undo (off the tape page; the tape page has MINUS for that) */
    { 0x36, 55 },   /* PLUS (light only): the press is the right arrow; Shift + PLUS = Move + (octave up) */
    { 0x37, 54 },   /* MINUS (light only): the press is the left arrow; Shift + MINUS = Move - (octave down) */
    { 0x0C, 43 },   /* B1  -> left button 1 (top)    */
    { 0x0D, 41 },   /* B2  -> left button 3 = FX / MIXER (the mixer first; again: reverb, delay...) */
    { 0x0E, 40 },   /* B3  -> left button 4 = TAPE */
    { 0x24, 50 },   /* SAMPLE SELECT  -> Menu (Shift + Menu: export) */
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
static volatile int page_tape;              /* Console's tape page is showing (written by the screen thread): the pads are step buttons there */
static volatile int page_tapeonly;          /* the tape recorder page itself (not the instrument list, song or mixer): its own button layout */
static volatile int page_seq;               /* a sequencer page (drum or synth): K1 is also sent as its absolute position */
static volatile int page_retrig;            /* a sound page, or steps selected: knob mode re-plays the drum while a knob is turned (not on song, punch FX, automation, LFO, mixer ...) */
static volatile int page_sound;             /* the instrument's sound / parameter page that has a sequencer: SEQ goes to it (as B1 does) */
static volatile int page_nostep;            /* a page with no steps (the sound page): SEQ does nothing there and step mode / step settings don't apply (written by the screen thread) */
static volatile int page_param;             /* a step is selected on the sequencer page (written by the screen thread): the pads are its settings, as with param_mode */
static volatile int page_linear;            /* a synth is the instrument (second letter "y" in /tmp/console-pagemode): the note pads are Move pads 1-16 (bank: 17-32) in order, so the scale runs on up the rows instead of skipping the Move's right half */
static int param_mode;                      /* Shift + SEQ: the pads are Move pads 1-32 in order (a step's settings), bank = 1-16 / 17-32 */
static int pad_knob[16];                    /* knob mode: which Move knob (0-7) each held pad is touching, -1 none */
static int knob_stamp[16], knob_clock;      /* ... and the order they were pressed (the last one wins) */
static int shift_held, stop_target = -1;     /* STOP: stops playback (Play) while playing, else Back; Shift + STOP = Back */
static long tick_n, last_turn = -100000, retrig_at, retrig_off;   /* one tick per audio period (about 2.9 ms) */
static int last_drum = -1, retrig_on;       /* the last drum pad played, and its Move note while it is being retriggered */
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
        int v = (page_param && shift_held && !knob_mode) ? move_step[i]                       /* steps selected + Shift held: the steps, to add or take off more */
              : ((param_mode && !page_nostep) || page_param) ? move_pad[i + (right_bank ? 16 : 0)] : ((step_mode && !page_nostep) || page_tape) ? move_step[i] : move_pad[page_linear ? i + (right_bank ? 16 : 0) : (i / 4) * 8 + (i % 4) + (right_bank ? 4 : 0)];
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
    set_btn_light(MPC_SEQ, (step_mode || param_mode) && !page_nostep && !page_tapeonly);
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
/* K1-K3 and FADER are potentiometers (absolute 0-127, a stop at each end), a Move knob is endless. The clicks come from the
   movement. K1 is also sent as its absolute position (CC 112, 0-127): Console's MPC layer uses it to set a pattern's length directly
   from where the knob is (1-64), which the clicks alone could not do. */
static void knob_clicks(int slot, int val, int move_cc)
{
    if (slot == 0 && page_seq) send3(0xBF, 112, val);                 /* (on the sequencer pages) */
    if (knob_last[slot] < 0) { knob_last[slot] = val; return; }
    int d = val - knob_last[slot];
    knob_last[slot] = val;
    if (d == 0) return;
    int n = d < 0 ? -d : d;
    if (n > 40) n = 40;
    for (int i = 0; i < n; i++) send3(0xBF, move_cc, d > 0 ? 1 : 127);
}

/* The MAIN VOLUME knob is absolute, Console's volume is 50 clicks of 2 % each (CC 79 relative). The first move syncs them
   (50 clicks down = 0, then up to where the knob is); after that the knob always means the same volume. */
#define VOL_CLICKS 50
static int vol_est = -1;
static void volume_knob(int val)
{
    int target = (val * VOL_CLICKS + 63) / 127;
    if (vol_est < 0) {
        for (int i = 0; i < VOL_CLICKS; i++) send3(0xBF, 79, 127);
        vol_est = 0;
    }
    int d = target - vol_est;
    for (int i = 0; i < (d < 0 ? -d : d); i++) send3(0xBF, 79, d > 0 ? 1 : 127);
    vol_est = target;
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
    if (on && shift_held && !knob_mode && page_tape && idx >= 8) {
        /* Shift + pad, as printed on the pads, on the tape-style pages (pads 9-16 are free there; 1-8 arm / solo):
           16 PROJECT = the menu, 12 SONG = the song page, 14 TIME CORRECT = the next grid (tape page only). Private CCs: mpcui/stepentry.py.
           (Not on instrument pages: Shift + pad picks a pattern there, and with SEQ on it selects a step.) */
        int cc = idx == 15 ? 109 : idx == 11 ? 110 : (idx == 13 && page_tapeonly) ? 111 : 0;
        if (cc) { send3(0xBF, cc, 127); send3(0xBF, cc, 0); return; }
    }
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
        int note = (page_param && shift_held) ? 16 + idx                                       /* (Shift + a pad while steps are selected: that step, with Shift = in / out of the selection) */
                 : ((param_mode && !page_nostep) || page_param) ? 68 + idx + (right_bank ? 16 : 0)
                 : ((step_mode && !page_nostep) || page_tape) ? 16 + idx : page_linear ? 68 + idx + (right_bank ? 16 : 0) : 68 + (idx / 4) * 8 + (idx % 4) + (right_bank ? 4 : 0);
        pad_target[idx] = note;
        if ((!step_mode || page_nostep) && (!param_mode || page_nostep) && !page_param && !page_tape) last_drum = note;
        send3(0x9F, note, vel > 0 ? vel : 100);
    } else if (pad_target[idx] >= 0) {
        send3(0x8F, pad_target[idx], 0);
        pad_target[idx] = -1;
    }
}

/* While a knob-mode pad is held and the encoder is being turned (and the sequence is not playing), the last drum
   you played sounds again about every 0.4 s, so you can hear the parameter change. Called once per audio period. */
#define RETRIG_EVERY 140                     /* ticks: about 0.4 s */
#define RETRIG_LEN 35                        /* about 0.1 s */
#define RETRIG_WHILE 230                     /* keeps going this long after the last turn: about 0.7 s */
static void mapping_tick(void)
{
    tick_n++;
    { static int seen; int now = page_tape * 8 + page_tapeonly * 16 + page_param * 2 + page_nostep + page_linear * 32; if (seen != now) { seen = now; if (page_tapeonly && knob_mode) { release_knob_pads(); knob_mode = 0; } refresh_pads(); refresh_buttons(); } }     /* the pads change meaning on the tape page: new lights */
#ifdef NO_RETRIG
    return;
#endif
    if (retrig_on && tick_n >= retrig_off) { send3(0x8F, retrig_on, 0); retrig_on = 0; }
    if (!knob_mode || !page_retrig || last_drum < 0 || move_btn[85] || held_knob() < 0 || tick_n - last_turn > RETRIG_WHILE) return;
    if (!retrig_on && tick_n >= retrig_at) {
        send3(0x9F, last_drum, 100);
        retrig_on = last_drum; retrig_off = tick_n + RETRIG_LEN; retrig_at = tick_n + RETRIG_EVERY;
    }
}

#define MPC_SHIFT 0x31
#define MPC_STOP  0x51
static void mpc_button_event(int note, int down)
{
    if (note == MPC_SHIFT) { shift_held = down; if (page_param) refresh_pads(); }      /* (steps selected: the pads show the steps while Shift is held) */
    if (note == MPC_STOP) {
        if (down) stop_target = (!shift_held && move_btn[85]) ? 85 : 51;   /* move_btn[85]: Console's Play light = playing */
        if (stop_target >= 0) send3(0xBF, stop_target, down ? 127 : 0);
        if (!down) stop_target = -1;
        return;
    }
    if (note == MPC_ENC_PUSH) { send3(0xBF, 3, down ? 127 : 0); return; }
    if (page_tapeonly && note != MPC_SHIFT) {                         /* the tape page has its own layout */
        static uint8_t alt[128];                                       /* a button pressed with Shift is released as that, whatever Shift does by then */
        if (down) alt[note] = shift_held;
        int was_alt = alt[note];
        switch (note) {
        case 0x35:                                                     /* Shift + TAP TEMPO = the metronome on / off (it clicks while recording) */
            if (was_alt && down) send3(0xBF, 108, 127);
            return;
        case MPC_KNOBFX: case MPC_SEQ: case MPC_PADBANK: case 0x01: case 0x28:
            return;                                                    /* KNOB FX, SEQ, PAD BANK, PAD FX, 16 LEVELS: nothing here */
        case 0x0B: send3(0xBF, 52, down ? 127 : 0); return;           /* NOTE REPEAT = Drop (Shift: Drop and push the rest later) */
        case 0x09:                                                     /* ERASE = Cut; Shift + ERASE = Copy (Console must not see Shift on it) */
            if (was_alt) { if (down) { send3(0xBF, 49, 0); send3(0xBF, 60, 127); send3(0xBF, 49, 127); } else send3(0xBF, 60, 0); }
            else send3(0xBF, 119, down ? 127 : 0);
            return;
        case 0x36: case 0x37:                                          /* MINUS = Undo, PLUS = Redo; Shift + them = zoom (the Move's + / -) */
            if (!was_alt) { send3(0xBF, note == 0x36 ? 104 : 56, down ? 127 : 0); return; }
            break;
        case 0x4A:                                                     /* LOOP = loop on / off; Shift + LOOP = set a loop point (Console works out in or out) */
            if (was_alt) { if (down) send3(0xBF, 105, 127); return; }
            break;
        case 0x49: if (down) send3(0xBF, 106, 127); return;           /* SAMPLE REC = arm / disarm the selected track */
        }
    }
    if (note == MPC_SEQ && page_sound && !shift_held) { send3(0xBF, 43, down ? 127 : 0); return; }   /* the sound page: SEQ = its sequencer (B1) */
    if (note == MPC_SEQ && page_nostep) return;                       /* a page with no steps: SEQ does nothing (and nothing carries over to the next page) */
    if (note == MPC_SEQ && page_param && !shift_held) {                  /* steps selected: SEQ = done with them (a tap on any step, as Console has it) */
        if (down) { send3(0x9F, 16, 100); send3(0x8F, 16, 0); }
        return;
    }
    if (down && note == MPC_SEQ) {
        if (shift_held) param_mode = !param_mode;                     /* Shift + SEQ: the pads are a step's settings */
        else if (param_mode) { param_mode = 0; step_mode = 1; }       /* SEQ from there: back to the steps */
        else step_mode = !step_mode;
        refresh_pads(); refresh_buttons(); return;
    }
    if (down && note == MPC_PADBANK) { right_bank = !right_bank; refresh_pads(); refresh_buttons(); return; }
    if (down && note == MPC_KNOBFX) { release_knob_pads(); knob_mode = !knob_mode; refresh_pads(); refresh_buttons(); return; }
    if (note == MPC_SEQ || note == MPC_PADBANK || note == MPC_KNOBFX) return;
    if ((note == 0x36 || note == 0x37) && page_seq) {          /* a sequencer page: Shift + MINUS = Undo, Shift + PLUS = Redo (as printed on the buttons) */
        static uint8_t sq[2];
        int i = note == 0x37;
        if (down) sq[i] = shift_held;
        if (sq[i]) { send3(0xBF, i ? 56 : 104, down ? 127 : 0); if (!down) sq[i] = 0; return; }
    }
    if (note == 0x36 || note == 0x37) {                   /* PLUS / MINUS = right / left arrow; with Shift: the Move's + / - */
        int plus = note == 0x36;
        if (!shift_held) send3(0xBF, plus ? 63 : 62, down ? 127 : 0);
        else if (down) { send3(0xBF, 49, 0); send3(0xBF, plus ? 55 : 54, 127); send3(0xBF, 49, 127); }   /* Console must not see Shift on it */
        else send3(0xBF, plus ? 55 : 54, 0);
        return;
    }
    if (note == 0x35 && shift_held && page_seq) {            /* a sequencer page: Shift + TAP TEMPO = the metronome on / off (as on the tape page) */
        if (down) send3(0xBF, 108, 127);
        return;
    }
    if (note == 0x0B && shift_held) {                       /* Shift + NOTE REPEAT (labelled TRIPLET): triplets on / off (Console's own undo moved to 16 LEVELS) */
        if (down) send3(0xBF, 107, 127);
        return;
    }
    if ((note == 0x0B && !shift_held) || note == 0x01) {   /* NOTE REPEAT = the arpeggiator page (Shift + step 3), PAD FX = the pads page (Shift + step 2);
                                                               Shift + NOTE REPEAT is still Undo. Both open on a synth's sound pages; again or Back returns */
        if (down) {
            int step = note == 0x0B ? 18 : 17;
            send3(0xBF, 49, 127); send3(0x9F, step, 100); send3(0x8F, step, 0); send3(0xBF, 49, 0);
        }
        return;
    }
    for (int i = 0; i < NBUTTONS; i++)
        if (BUTTONS[i].mpc == note) { send3(0xBF, BUTTONS[i].move, down ? 127 : 0); return; }
    if (down && page_param && !shift_held && note != MPC_SHIFT) {        /* steps selected: a button with no job on this page = done with them, like SEQ */
        send3(0x9F, 16, 100); send3(0x8F, 16, 0);
    }
}

static void mpc_cc_event(int cc, int val)
{
    switch (cc) {
    case 0x10: case 0x11: case 0x12:                      /* K1-K3 = Move knobs 1-3 */
        knob_clicks(cc - 0x10, val, 71 + (cc - 0x10));
        break;
    case 0x13: volume_knob(val); break;                   /* MAIN VOLUME -> Console's volume, absolute */
    case 0x14: knob_clicks(4, val, 74); break;            /* FADER -> knob 4 (the lane's SHIFT) */
    case 0x64: {                                          /* encoder: relative already */
        int k = held_knob();                              /* a knob-mode pad held: that knob; else the jog wheel */
        if (k >= 0) last_turn = tick_n;
        /* relative, two's complement: 01 / 7F = one notch up / down, but a quick turn sends bigger steps (02, 03 ... 7E, 7D ...).
           Only 7F used to count as "down": every other value, a quick turn left included, went up. */
        int dir = val >= 64 ? 127 : 1;
        int notches = val >= 64 ? 128 - val : val;
        if (notches < 1) notches = 1;
        if (notches > 8) notches = 8;
        for (int i = 0; i < notches * (k >= 0 ? KNOB_STEP : 1); i++)   /* the MPC encoder is slow next to a Move knob: several clicks per notch */
            send3(0xBF, k >= 0 ? 71 + k : 14, dir);
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
