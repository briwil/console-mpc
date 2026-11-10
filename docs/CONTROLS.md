# Console on the MPC Sample: what each control does (first layout, Nov 2026)

The bridge (bridge/mapping.h) makes MPC controls look like the Move's. Every row is easy to change.

| MPC control | Console (Move) function |
|---|---|
| B1, B2, B3, PAD FX | Left buttons 1-4 (top to bottom): instruments, song mode, FX, tape recorder |
| Pads 1-16 | The left 4x4 pads (the drums) |
| PAD BANK (latching) | Pads become the right 4x4 (chromatic) |
| SEQ (latching) | Pads become the 16 step buttons |
| K1, K2, K3 | Move knobs 1-3 (always) |
| KNOB FX (latching) | Knob mode: pads 1-8 = Move knobs 1-8. Hold a pad and turn the encoder; pads 9-16 are silent. No pad held: the encoder is the jog wheel again |
| FADER | Move knob 8 |
| MAIN VOLUME | Volume knob |
| Encoder turn / push | Jog wheel turn / press |
| Sample Select (0x24) | Menu (Shift + Menu: export) |
| Button 0x06 (panel name unknown) | Left arrow (guess) |
| 0x4A (unidentified light) | Right arrow (guess; no button known yet) |
| PLUS / MINUS | Octave up / down |
| PLAY, SEQ REC, SAMPLE REC | Play, Record, Sample |
| STOP | While playing: stops playback. Otherwise: Back. Shift + STOP: always Back (saves and quits from the top level) |
| ERASE, MUTE, TAP TEMPO, NOTE REPEAT, CHOP, 16 LEVELS | Delete, Mute, Copy, Undo, Loop, Capture |
| SHIFT | Shift |

Start: `sh /data/UserData/console/mpc/mpc-console.sh` from the root shell. Quit: Shift + STOP.

## Starting without a computer
`sh /data/UserData/console/mpc/install-boot.sh` adds a startup menu (PAD 1 = Console, PAD 2 = stock MPC, no answer = MPC) to the SD card's autorun; `... install-boot.sh remove` undoes it; a file named NOCONSOLE on the SD card skips it once.
