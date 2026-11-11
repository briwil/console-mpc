# Console on the MPC Sample: what each control does (first layout, Nov 2026)

The bridge (bridge/mapping.h) makes MPC controls look like the Move's. Every row is easy to change.

| MPC control | Console (Move) function |
|---|---|
| B1 | Instruments; again goes round an instrument's pages: sound, sequencer, automation, punch FX, then SONG, then back |
| B2 | Mixer (again: reverb, delay, ...; Back leaves) |
| B3 | Tape recorder (again: the selected track zoomed) |
| PAD FX | The pads page of a synth (key, scale, octave, pad velocity and curve): the Move's Shift + step 2. Again: back |
| Song mode on / off | on the SONG page: Shift + PLUS / MINUS |
| Pads 1-16 | The left 4x4 pads (the drums) |
| PAD BANK (latching) | Pads become the right 4x4 (chromatic) |
| SEQ | not used |
| SEQ RECORD on a sequencer page (drums or synth) | Pads become the 16 steps (lit); again: back to the drums / notes. Leaving the page ends it. (On the tape page the pads are always the steps: 1-8 = tracks, Shift + step = arm) |
| K1, K2, K3 | Move knobs 1-3 (always) |
| KNOB FX (latching) | Knob mode: pads 1-8 = Move knobs 1-8. Hold a pad and turn the encoder; pads 9-16 are silent. No pad held: the encoder is the jog wheel again |
| FADER | Move knob 4 (lane shift, among others) |
| MAIN VOLUME | Volume: absolute (the first time you touch it, Console is synced to the knob) |
| Encoder turn / push | Jog wheel turn / press |
| Sample Select (0x24) | Menu (Shift + Menu: export) |
| LOOP | Loop (the tape's loop in / out) |
| PLUS / MINUS | Right / left arrow (settings pages, lane steps 17-32...) |
| Shift + PLUS / MINUS | Move + / - (octave on a sound page, pattern +/-) |
| PLAY, SEQ REC | Play, Record |
| CHOP | Splice (Shift + CHOP: splice all) |
| SAMPLE REC | not used yet |
| STOP | While playing: stops playback. Otherwise: Back. Shift + STOP: always Back (saves and quits from the top level) |
| NOTE REPEAT | The arpeggiator page of a synth (the Move's Shift + step 3). Again: back. Shift + NOTE REPEAT = Undo |
| ERASE, MUTE, TAP TEMPO, 16 LEVELS | Delete, Mute, Copy, Capture |
| SHIFT | Shift |

Start: `sh /data/UserData/console/mpc/mpc-console.sh` from the root shell. Quit: Shift + STOP.

## Starting without a computer
`sh /data/UserData/console/mpc/install-boot.sh` adds a startup menu (PAD 1 = Console, PAD 2 = stock MPC, no answer = MPC) to the SD card's autorun; `... install-boot.sh remove` undoes it; a file named NOCONSOLE on the SD card skips it once.

## Step settings and lane settings (the drum sequencer)

Step settings (velocity, chance, multiply, pulse, hold, jump, random, ramps, nudge, then the drum's own sounds):
1. SEQ on. Hold SHIFT and tap the steps you want (they blink).
2. Shift + SEQ: the pads are now the settings. Tap one (it's picked), turn K1 to set it (K2 = its chance). Tap the same pad again: it's off.
3. SEQ: back to the steps. Tap any step to finish.

Lane settings (no steps selected): K1 = length, K2 = rate, K3 = Euclid. Shift needs knob 4: KNOB FX on, hold pad 4, turn the encoder.
