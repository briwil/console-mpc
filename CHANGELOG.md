# Changelog

Each version is a release on the [Releases](https://github.com/briwil/console-mpc/releases) page with `Console-MPC.zip` attached.
To update, drag the new `autorun` and `Console` folders from the zip onto the SD card and choose Replace.

## 0.0.17

- **Start-up animation and welcome screen:** the animation is now only the green bent bars (no CONSOLE, bar or STARTING text), moved down to where the welcome screen has them, and the welcome screen's bars are exactly the animation's last frame (same thickness, curve and place).

## 0.0.16

- **Welcome screen:** the button groups line up with the buttons, the two bent bars are the instruments page's (same colours, thickness and curve), BTN 1 / 2 / 3 are centred in their boxes, and WELCOME TO CONSOLE sits a little higher and further left.

## 0.0.15

- **B1 / B2 / B3 shortcuts (every page):** Shift + B1, or holding B1, opens SETTINGS; Shift + B2 / hold B2 opens the Project menu (NEW, SAVE, LOAD, SETTINGS); Shift + B3 / hold B3 opens CHANGE / REMOVE for the instrument under the cursor. Pressing B1, B2 or B3 with one of these menus open closes it. Quit stays on Shift + STOP.

## 0.0.14

- **Tape page:** the wheel push splices (like CHOP); Shift + push sends the playhead to the start (or the loop's in point). STOP when already stopped does the same. K1 and the fader set the selected track's volume by position (0-100 %), K2 its pan.
- **Zoomed tape page:** a new layout: the track number, the reels (smaller), the time under them and the recording across the bottom as a coloured waveform with a ruler above. The wheel push splices there too.
- **Faster screen** on the tape pages: the waveforms and the reels are drawn on whole arrays.
- **Start-up screen** shows at once when Console starts (no flash of the last page).
- Fix: the count-in and the metronome click follow the volume knob and the metronome volume (they played at full level, and never fell below 40 %).

## 0.0.13

- **Tape page:** a recording is a filled box in its colour with the waveform in black, so each one reads clearly.

## 0.0.12

- **Tape page:** each recording gets its own muted colour (a splice's right half turns a new one), so the sections tell apart at a glance. The zoomed track's strip uses the same colours.

## 0.0.11

- **Song page:** SEQ opens the sequencer and SAMPLE page 1 of the instrument the white box is on. LOOP loops the song (off by default; shown in the title). In KNOB FX, pad 12 (orange) held + the wheel changes how many times a row PLAYS (the number grows while held), and only as many blue pads as the song has instruments light up. The shown row follows the playing row. An instrument a row doesn't name is silent in it.
- **Song end and STOP:** with loop off the song ends exactly at the end of its last row (no extra notes) and does not touch the tape: the tape keeps playing / recording (for the tails) until STOP. STOP cuts every note at once, including an arp running over a long note. STOP when already stopped sends the playhead to the start, or the loop's in point.
- **Tape page:** all 8 tracks on screen again, each with a small waveform instead of a bar, in subtle dark-grey boxes. K1 and the fader set the selected track's volume by position (0-100 %), K2 its pan (left end L100, middle centre, right end R100). Shift + wheel changes the grid.
- **Zoomed tape page:** about ten times less drawing time (the reels), and they turn half as far per beat.
- **Start-up screen** after each start: it stays until left button 1, 2 or 3 is pressed.
- **Wheel and knobs:** one click of the wheel is 1 % on number settings, K1 / K2 / K3 are pots on sound pages (their position is the value, end to end), K2 / K3 pick the tape inputs evenly. Every knob was checked for 1 click = 1 %.
- **Sequencer bars** on the synth sequencer scale with each note's velocity. A one-second pop-up names the pad mode (PADS / KNOB FX / SEQ / STEP SETTINGS).
- Fix: crackle in song mode (the sound of the instruments was switching between two paths every frame).
- Fix: updating (the update script checks the exact version, retries, and prints what it installed).

## 0.0.10

- **AUTOMATION page:** a list of the settings that have steps (8 rows to start, more as you add them; EMPTY rows open a picker of everything that can be automated). A setting opens as a pop-up: its steps on top (each bar as high as its value), VALUE and LENGTH below (pads 1 and 2, like the other pop-ups). Back returns to the list.
  - Sound settings get a lane of their own: any step can have a value, notes or not (a held note can be swept), and the lane has its own length. Velocity, chance and the other step settings stay on the notes (marked NOTES when a sound setting is locked on notes).
  - Set a step: hold it, pick several with Shift + steps (white boxes), or move the white box with the wheel and push to set a step on / off. In SEQ mode a pad sets a new step's value by how hard you hit it. K1's position is the value (halfway = halfway).
  - Record with record on and playing: knob 1 plays the setting live and lays it on the steps; it goes back to its value when recording ends.
- **Punch FX:** pad 3 = CHANCE for every step of the effect's lane. A pad with no setting no longer makes the others fade.
- **K1 on a step setting:** at an end stop the setting goes to its lowest / highest.
- **NEW PROJECT** lands on the INSTRUMENTS page.
- **Sequencer pages:** MINUS = Undo, PLUS = Redo; Shift + MINUS / PLUS = the previous / next 16 steps.
- **PAD FX is a pop-up** over the page you are on (like the ARP): knobs 1-5 are the pads' settings, PLUS / MINUS change the octave, the pads keep playing. PAD FX again or BACK closes it.
- **Live pattern recording:** COUNT IN clicks before PLAY starts the recording; a pass is one undo step; pads are recorded at the time you pressed them (the app's reading delay is taken off), and a pad at the very start lands on step 1.
- Fix: Shift + PLUS (redo) on a synth sequencer page crashed the app.

## 0.0.9

- **Per-note sequencer:** a note is always picked (the lowest pad at first). Tapping it again no longer jumps to an "all notes" lane, so the steps always belong to the note shown.
- Fix: the version label on the card no longer shows a stray `\n`.

## 0.0.8

- **ARP pop-up:** NOTE REPEAT opens the arp as a panel over the sound or sequencer page you are on, instead of its own page. KNOB FX comes on by itself (pads 1-8 are the settings, which grow as you turn them), pads 9-16 are orange and play notes, SEQ turns the pads into the arp's 16 steps (tap: note, accent, rest), PLUS / MINUS flip ARP / ARP 2, and PLAY and STOP work as always. NOTE REPEAT or BACK closes it.
- **MONOMODULE FX** as an insert effect (needs your own Monomachine OS file).
- Fix: in KNOB FX mode the wheel on pad 1 sets a sequencer's length, as the K1 knob does.

## 0.0.7

- **Instrument picker:** DRUMS and SYNTH cards separate the two groups; each holds for a second, then the list moves on.
- Hold the wheel push on a loaded instrument for CHANGE / REMOVE (same as Shift + push).
- Fix: turning K1 on a sequencer no longer jumps back to the sound page (its position and the SAMPLE key shared a controller number). It sets the pattern length again.
- One MODEL-72 (the Move-only copy that made no sound is gone). 9W9 is removed.

## 0.0.6

- **VST2 instruments:** Console hosts VST2 synths as well as effects: MODEL-72, PROFIT-5, JN-106, STURM-TP, MONOMODULE, CLEMENTINE, OXZYGEN, the OP-1 Suite (11 instruments, with 8 Console presets each). Put each plug-in's `.so` (and its data folders) in `ConsoleData/plugins`; they are not included.
- **More inserts:** the OP-1 effects (with their own presets), VHS VIBES and BORIS.
- Thumbnails for all of them.
- Plug-in data folders in `ConsoleData/plugins` are copied to the internal drive on start.

## 0.0.5

- **GUITAR instrument:** plays the Sample's audio input (your guitar, in the back jacks) through Stompbox, built in: 40 presets (amps, pedals, cabinet, effects) on the PRESETS page, its settings on the sound page. Pick it as an instrument and play; arm its track on the tape page to record live. No sequencer, automation, PUNCH FX or song pages, and no patterns on it. The input is switched to REAR while GUITAR is loaded and put back afterwards. It needs `stompbox.so` (64-bit ARM, from the plugin's Sample release) in `/data/UserData/console/plugins`.
- **STOMPBOX as an insert effect** (and any other VST2 effect put in `plugins`): Console can run VST2 audio effects as an instrument's insert effect.
- **COUNT IN** (SETTINGS): 1, 2 or 4 bars of clicks before a recording starts.
- **Metronome:** Shift + TAP TEMPO switches it on and off on the tape page and on the sequencer pages (it clicks while a sequence plays there); the SETTINGS row pushes it on / off and the wheel sets its volume.
- SEQ on an instrument's sound page goes to its sequencer.
- INSERT pages are titled INSERT 1 / INSERT 2, and SENDS no longer says which slot.
- SETTINGS: no UPDATE row (update over SSH), no OP-XY wording in SYNC.
- The audio inputs are on by default (the file `DISABLE_INPUT` in `/data/UserData/console` turns them off).
- The volume knob no longer shows a cut-off "OUTPUT IS ..." message.
- Console's own code now lives in this repo (the `console` folder), so building the card no longer needs the Move repo.

## 0.0.4

- Steps selected: any button with no job on that page now finishes the selection, like SEQ, STOP and BACK.

## 0.0.3

- Selecting steps (Shift + pads): while steps are selected, holding Shift shows the step pads again so you can add or remove steps with the pads, not only with the wheel's box. SEQ finishes the selection.
- Developers: `authorized_keys` and `ssh_host_ed25519_key` can live in a `ConsoleDev` folder on the card, so updating (which replaces `autorun`) no longer removes them.
- A step laid down from the pads keeps the pad's velocity, with the PADS page's curve or fixed velocity applied: SEQ pad taps, drum hits recorded live, and a chromatic pad on a held step (drums), and SEQ pad taps on a synth. The step bars show it, taller for harder.
- The LFO's DEST names the drum on a drum machine: "SNR DECAY" instead of just "DECAY".

## 0.0.2

- Shift + K1, K2, K3 and the FADER now really are knobs 5-8 on an instrument's pages (its sound pages, LFO / INSERT / SENDS / PADS / ARP) and the song insert pages. In 0.0.1 this didn't work: the code that turns it on failed at start-up.
- On those pages and the sequencers, Shift + a knob is the same as the knob alone (no one-step fine adjust). The mixer and tape pages keep Shift + knob = pan.

## 0.0.1

First release of Console for the Akai MPC Sample (firmware 1.3.0).

- The 8-track recorder, drum and synth sequencers, song mode, mixer, inserts, FX and Ducker, on the Sample's own screen, pads, knobs and wheel.
- A startup menu: PAD 1 = Console, PAD 2 = the normal MPC.
- The startup menu finds the panel's MIDI port by name, so the pads work on every boot.
- No loud pop when Console starts.
- Your projects, presets and settings live in `ConsoleData`, a folder of their own on the card, so replacing the `Console` and `autorun` folders (the way to update) can't delete them. A copy is kept on the Sample and refills the card if it ever loses `ConsoleData`.
- The wheel reads quick turns in the right direction.
- Shift + K1, K2, K3 and the FADER are knobs 5-8 on the drum / synth sound pages and the insert pages. Shift + turn is no longer a one-step fine adjust.
- The sound page's grow animation keeps real-time speed on slow frames, and a turned setting shrinks after 0.5 s (at once when its KNOB FX pad is let go).
- A manual: [consoleforthesample.com](https://consoleforthesample.com).
