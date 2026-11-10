# Console on the MPC Sample: what each control does (first layout, Nov 2026)

The bridge (bridge/mapping.h) makes MPC controls look like the Move's. Every row is easy to change.

| MPC control | Console (Move) function |
|---|---|
| B1, B2, B3, PAD FX | Left buttons 1-4 (top to bottom): instruments, song mode, FX, tape recorder |
| Pads 1-16 | The left 4x4 pads (the drums) |
| PAD BANK (latching) | Pads become the right 4x4 (chromatic) |
| SEQ (latching) | Pads become the 16 step buttons |
| Shift + SEQ | Pads become a step's settings: Move pads 1-32 in order (PAD BANK flips 1-16 / 17-32). SEQ again goes back to the steps |
| K1, K2, K3 | Move knobs 1-3 (always) |
| KNOB FX (latching) | Knob mode: pads 1-8 = Move knobs 1-8. Hold a pad and turn the encoder; pads 9-16 are silent. No pad held: the encoder is the jog wheel again |
| FADER | Move knob 4 (lane shift, among others) |
| MAIN VOLUME | Volume: absolute (the first time you touch it, Console is synced to the knob) |
| Encoder turn / push | Jog wheel turn / press |
| Sample Select (0x24) | Menu (Shift + Menu: export) |
| LOOP | Loop (the tape's loop in / out) |
| PLUS / MINUS | Right / left arrow (settings pages, lane steps 17-32...) |
| Shift + PLUS / MINUS | Move + / - (octave on a sound page, pattern +/-) |
| PLAY, SEQ REC, SAMPLE REC | Play, Record, Sample |
| STOP | While playing: stops playback. Otherwise: Back. Shift + STOP: always Back (saves and quits from the top level) |
| ERASE, MUTE, TAP TEMPO, NOTE REPEAT, 16 LEVELS | Delete, Mute, Copy, Undo, Capture |
| CHOP | not used yet |
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
