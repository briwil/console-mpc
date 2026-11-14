# Console on the MPC Sample: what each control does (first layout, Nov 2026)

The bridge (bridge/mapping.h) makes MPC controls look like the Move's. Every row is easy to change.

| MPC control | Console (Move) function |
|---|---|
| B1 | Instruments; again goes round an instrument's pages: sound, sequencer, automation, punch FX, then SONG, then back |
| B2 | Mixer (again: reverb, delay, ...; Back leaves) |
| B3 | Tape recorder (again: the selected track zoomed) |
| PAD FX | The pads page of a synth (key, scale, octave, pad velocity and curve): the Move's Shift + step 2. Again: back |
| Song mode on / off | on the SONG page: PLUS / MINUS (Shift + them too) |
| Pads 1-16 | The left 4x4 pads (the drums) |
| PAD BANK (latching) | Pads become the right 4x4 (chromatic) |
| SEQ (latching) | Pads become the 16 step buttons (on the tape page they always are: step 1-8 = tracks, Shift + step = arm) |
| Shift + SEQ | Pads become a step's settings: Move pads 1-32 in order (PAD BANK flips 1-16 / 17-32). SEQ again goes back to the steps |
| K1, K2, K3 | Move knobs 1-3. On an instrument's pages (sound, LFO, INSERT, SENDS, PADS, ARP) and the song insert pages, Shift + K1, K2, K3 and Shift + FADER are knobs 5-8 |
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
| NOTE REPEAT | The arpeggiator page of a synth (the Move's Shift + step 3). Again: back. Shift + NOTE REPEAT = triplets on / off |
| ERASE, MUTE, TAP TEMPO, 16 LEVELS | Delete, Mute, Copy, Capture |
| SHIFT | Shift |

Start: `sh /data/UserData/console/mpc/mpc-console.sh` from the root shell. Quit: Shift + STOP.

## The tape page (8 tracks, 4 on screen; also the zoomed track)

| Control | Does |
|---|---|
| Shift + wheel | Scroll through the 8 tracks |
| K1 / K2 / FADER | The selected track: K1 = volume, K2 = pan, FADER = volume (Shift + FADER: pan). K3 does nothing |
| Shift + TAP TEMPO | Metronome on / off: it clicks while recording. Its volume: SETTINGS > METRONOME |
| Shift + wheel push | Next grid (1/4, 1/8 ...) |
| Shift + pad | Arm / disarm that track. SAMPLE REC: arm / disarm the selected track |
| Shift + pad 16 / 12 / 14 | As printed: PROJECT = the menu, SONG = the song page, TIME CORRECT = the next grid. (16 and 12 also work on the instrument list, song and mixer pages. Not on instrument pages: Shift + pad picks a pattern there) |
| MINUS / PLUS | Undo / Redo. Shift + them: zoom out / in |
| CHOP | Split / join the box under the playhead (Shift: all tracks) |
| ERASE | Cut (hold, move to take several, let go). Shift + ERASE: Copy |
| NOTE REPEAT | Drop (Shift: drop and push the rest later) |
| LOOP | Loop on / off. Shift + LOOP: the first press marks a loop point, the second sets the other (earlier = IN, later = OUT). Both at the same spot: points cleared |
| KNOB FX, SEQ, PAD BANK, PAD FX, TAP TEMPO, 16 LEVELS | do nothing here |

On the drum and synth sequencer pages: Shift + MINUS = Undo, Shift + PLUS = Redo (as printed on the buttons; PLUS / MINUS alone are still the arrows).

Off the tape page: Shift + NOTE REPEAT (labelled TRIPLET) turns triplets on / off; 16 LEVELS is Undo (the sequencer's undo too).

## Starting without a computer
`sh /data/UserData/console/mpc/install-boot.sh` adds a startup menu (PAD 1 = Console, PAD 2 = stock MPC, no answer = MPC) to the SD card's autorun; `... install-boot.sh remove` undoes it; a file named NOCONSOLE on the SD card skips it once.

## Step settings and lane settings (the drum sequencer)

Step settings (velocity, chance, multiply, pulse, hold, jump, random, ramps, nudge, then the drum's own sounds):
1. SEQ on. Hold SHIFT and tap the steps you want (they blink). While steps are selected, holding Shift shows the steps on the pads again, so you can add more (or tap a selected one to take it out). To finish: SEQ, BACK, STOP, or any button that has no job on that page.
2. Let go of Shift: the pads are now the settings (orange). Tap one (it's picked), turn K1 to set it (K2 = its chance). Tap the same pad again: it's off.
3. Done: press SEQ (or STOP/BACK; while playing, the first STOP stops playback). The steps stop blinking and the pads are the steps again.

Lane settings (no steps selected): K1 = length, K2 = rate, K3 = Euclid. Shift needs knob 4: KNOB FX on, hold pad 4, turn the encoder.

Drum sequencer with the wheel: push on an empty step puts it down; push on a step that is on adds it to the selected steps (push it again: it leaves them); BACK: none selected. ERASE takes the selected steps off (none selected: the step under the box). Leaving the sequencer page deselects.

Recording into a sequencer keeps your timing (SETTINGS > REC TIMING: FREE). A hit lands on the nearest step and the step's NUDGE is set to how early or late you played (drums: 10% of a step at a time, synth notes: 1%; half a step at most). GRID: recording snaps to the steps.

Where things are saved: projects, presets and settings go to the SD card, in `ConsoleData` (made if it isn't there; the first time, what was on the card in `Console/data` or the internal drive is copied across). No card: the internal drive.

Stress test (Console's own): `echo 60 > /data/UserData/console/stress` over SSH (60 = minutes); the report is `console/stress-report.txt`. Shift + STOP ends it early.

Audio inputs are off unless turned on: `sh tools/input-check.sh on` from the Mac (`off` to turn them off, no argument: a report of the sound card).

Synth pads: the 16 pads play 16 notes of the scale in order (pad 5 is the 5th note); PAD BANK gives the next 16.

PRESETS page (synths): the box shows the preset you're on. The wheel turns the pages as everywhere else; push the wheel for the list, turn to hear presets, push to keep one, Back for the sound you had. Knob 1: the bank.

Audio input: MENU > SETTINGS > INPUT = REAR (the jacks on the back), MIC (the built-in microphone) or USB (what a computer plays to "MPC Sample Audio"). A track's input then offers that input's LEFT and RIGHT. The REC GAIN knob on the back sets the level of REAR and MIC.
