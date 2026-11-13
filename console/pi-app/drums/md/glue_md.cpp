/* The Machinedrum for Console: 16 lanes, each any TRX, EFM, P-I or GND machine with its eight controls.
 *
 * The sounds are OP-XY-MNMD's (vendor/, MIT): written from scratch for the OP-XY, voiced at 44.1 kHz and made
 * in blocks of 64 samples. Each lane is one voice, as a Machinedrum track is (a new hit restarts it). The
 * lanes share md::Common, so the hats choke each other as on the original.
 *
 * drums.py calls these through ctypes, as it does the 606 and 808 (one engine per library file; it loads a
 * second copy for the engine you play by hand):
 *   sw_init(rate)                         -> 16 (the voices)
 *   md_set(lane, what, value)             what 0-7: a control 0..127; 8: the machine (0..md_count()-1); 9: level
 *   sw_trigger(lane, velocity)
 *   sw_render(out, frames)                out: frames x 16 floats, each lane on its own
 * Hits land at the start of the next 64-sample block, so up to 1.5 ms late.
 */
#include <string.h>
#include "md_kit.hpp"
#include "md_dispatch.h"
#include "md_catalog.h"

namespace {
using opxy::i32;
using opxy::u32;
const int LANES = 16;
const unsigned B = opxy::block_frames;

struct Lane {
    int machine;
    int values[8];      // the controls, 0..127
    int level;          // 0..127
    float gain;         // the last hit's velocity
    int pending;        // a hit waiting for the next block
    MdState state;
    float out[B];
};

struct Engine {
    md::Common common;
    Lane lane[LANES];
    unsigned pos;       // where the next sample comes from in the current block
    u32 pitch[B];
};

Engine* E = 0;

void start_machine(Lane& l, int lane) {
    memset(&l.state, 0, sizeof l.state);
    md_reset(l.machine, l.state, E->common, (u32)lane + 1);
}

void make_block() {
    i32 slots[8], raw[B];
    for (int n = 0; n < LANES; ++n) {
        Lane& l = E->lane[n];
        const MdMachine& m = md_machines[l.machine];
        if (l.pending) {
            l.pending = 0;
            md_reset(l.machine, l.state, E->common, (u32)n + 1);
            md_trigger(l.machine, l.state, E->common);
        }
        for (int s = 0; s < 8; ++s) {        // 0..127 as the voices read it (an empty slot reads 0)
            const int v = l.values[s];
            slots[s] = !m.labels[s][0] ? 0 : v >= 127 ? 0x7fffffff : (i32)((u32)v * 16909320u);
        }
        md_render(l.machine, l.state, E->common, raw, slots, E->pitch);
        // a voice peaks at half scale: that's 1.0 here at LEVEL 127
        const float g = l.gain * (float)l.level / 127.0f / 1073741824.0f;
        for (unsigned i = 0; i < B; ++i) l.out[i] = (float)raw[i] * g;
    }
    E->pos = 0;
}
}

extern "C" {
int sw_init(float sample_rate)
{
    (void)sample_rate;                       // the voices are made for 44.1 kHz, which Console runs at
    if (!E) {
        E = new Engine;
        memset(E, 0, sizeof *E);
        for (unsigned i = 0; i < B; ++i) E->pitch[i] = md::kit::middle_c;
        for (int n = 0; n < LANES; ++n) {
            Lane& l = E->lane[n];
            l.machine = md_kit[n].machine;
            for (int s = 0; s < 8; ++s) l.values[s] = md_kit[n].values[s];
            l.level = 100;
            l.gain = 1.0f;
            start_machine(l, n);
        }
        E->pos = B;
    }
    return LANES;
}
int sw_voices(void) { return LANES; }
int md_count(void) { return MD_MACHINES; }
const char* md_name(int m) { return m >= 0 && m < MD_MACHINES ? md_machines[m].name : ""; }
const char* md_short(int m) { return m >= 0 && m < MD_MACHINES ? md_machines[m].shortname : ""; }
const char* md_label(int m, int slot)
{
    return m >= 0 && m < MD_MACHINES && slot >= 0 && slot < 8 ? md_machines[m].labels[slot] : "";
}
int md_default(int m, int slot)
{
    return m >= 0 && m < MD_MACHINES && slot >= 0 && slot < 8 ? md_machines[m].defaults[slot] : 0;
}
int md_kit_machine(int lane) { return lane >= 0 && lane < MD_LANES ? md_kit[lane].machine : 0; }
int md_kit_value(int lane, int slot)
{
    return lane >= 0 && lane < MD_LANES && slot >= 0 && slot < 8 ? md_kit[lane].values[slot] : 0;
}
const char* md_kit_role(int lane) { return lane >= 0 && lane < MD_LANES ? md_kit[lane].role : ""; }

void md_set(int lane, int what, int value)
{
    if (!E || lane < 0 || lane >= LANES)
        return;
    Lane& l = E->lane[lane];
    if (value < 0) value = 0;
    if (what >= 0 && what < 8) {
        l.values[what] = value > 127 ? 127 : value;
    } else if (what == 8) {
        const int m = value < MD_MACHINES ? value : MD_MACHINES - 1;
        if (m != l.machine) {
            l.machine = m;
            l.pending = 0;
            start_machine(l, lane);
        }
    } else if (what == 9) {
        l.level = value > 127 ? 127 : value;
    }
}
void sw_trigger(int lane, int velocity)
{
    if (!E || lane < 0 || lane >= LANES || velocity <= 0)
        return;
    E->lane[lane].pending = 1;
    E->lane[lane].gain = velocity > 127 ? 1.0f : (float)velocity / 127.0f;
}
void sw_render(float* out, int frames)
{
    if (!E)
        return;
    for (int f = 0; f < frames; ++f) {
        if (E->pos >= B)
            make_block();
        for (int n = 0; n < LANES; ++n)
            out[f * LANES + n] = E->lane[n].out[E->pos];
        ++E->pos;
    }
}
}
