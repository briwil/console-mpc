# Console on the MPC Sample: what each control does (first layout, Nov 2026)

The bridge (bridge/mapping.h) makes MPC controls look like the Move's. Every row is easy to change.

| MPC control | Console (Move) function |
|---|---|
| B1, B2, B3, PAD FX | Left buttons 1-4 (top to bottom): instruments, song mode, FX, tape recorder |
| Pads 1-16 | The left 4x4 pads (the drums) |
| PAD BANK (latching) | Pads become the right 4x4 (chromatic) |
| SEQ (latching) | Pads become the 16 step buttons |
| K1, K2, K3 | Move knobs 1-3; KNOB FX (latching) cycles to 4-6, then 7-8 |
| FADER | Move knob 8 |
| MAIN VOLUME | Volume knob |
| Encoder turn / push | Jog wheel turn / press |
| Sample Select (0x24) | Left arrow (guess) |
| 0x4A (unidentified light) | Right arrow (guess; no button known yet) |
| PLUS / MINUS | Octave up / down |
| PLAY, SEQ REC, SAMPLE REC | Play, Record, Sample |
| STOP | Back (Shift + Back saves and quits) |
| ERASE, MUTE, TAP TEMPO, NOTE REPEAT, CHOP, 16 LEVELS, SAMPLE | Delete, Mute, Copy, Undo, Loop, Capture, Menu |
| SHIFT | Shift |

Start: `sh /data/UserData/console/mpc/mpc-console.sh` from the root shell. Quit: Shift + STOP.
