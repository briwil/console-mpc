# Console on the Ableton Move

This repo started as a copy of `briwil/console` (the Pi 5 version). This folder holds everything
specific to running it on an Ableton Move.

## The Move (as found, Nov 2026)
- Move firmware 2.1.1 — do not update.
- 64-bit ARM (aarch64), glibc Linux with BusyBox tools (no `head -5`; use `head -n 5`).
- 1.8 GB RAM. System partition is nearly full: put everything in `/data/UserData`.
- Python 3.10 is installed; no pip, no numpy, no pygame. Has internet over Wi-Fi.
- SSH: `ssh ableton@move.local`. The Mac's `~/.ssh/config` uses `~/.ssh/move_key` for move.local;
  that public key is the one saved at `http://move.local/development/ssh`.
- `ps` only shows your own processes.

## Audio / controls / screen
RNBO Move Takeover (Cycling '74) is installed. It includes a custom JACK (`/data/UserData/rnbo/bin/jackd -d move`,
libs in `/data/UserData/rnbo/lib`) whose Move driver exposes:
- `system:capture_1/2`, `system:playback_1/2` — stereo, 16-bit, 44100 Hz, fixed 128-sample buffer.
- `system:midi_capture` / `system:midi_playback` — the Move's own controls and lights, MIDI channel 16.
- `system:midi_capture_ext` / `system:midi_playback_ext` — USB MIDI gear.
- `system:display` — send one MIDI event of 1032 bytes: `MOVEDISP` + 1024 bytes.
  Screen is 128 x 64, 1 bit: 8 strips of 128 bytes, each byte 8 pixels going down (bit 0 = top).

Control map (all channel 16):
| Control | Message |
|---|---|
| Pads | notes 68-99, velocity = how hard. 68-75 is the bottom row (left to right), 92-99 the top |
| Knobs 1-8 turn | CC 71-78; 1 = one click right, 127 = one click left |
| Knob touch | notes 0-9, 127 touched / 0 released |
| Step buttons | notes 16-31 |
| Left-side buttons | CC 43 (top), 42, 41, 40 (bottom); 127 / 0 |
| Volume knob | CC 79 (touch: note 8) |
| Jog wheel | turn CC 14 (1 = right, 127 = left), press CC 3, touch note 9 |
| Buttons (CC, 127 down / 0 up) | Play 85, Record 86, Sample 118, Loop 58, Shift 49, Menu 50, Back 51, Capture 52, Undo 56, Copy 60, Delete 119, Mute 88, + 55, - 54, left 62, right 63 |
| Jacks (plug detect) | CC 114: mic 0 / line in 127; CC 115: speaker 0 / line out 127 |
Pad lights: note on, channel 16, note = pad, velocity = colour (127 worked); 0 = off.
(Button numbers and names confirmed on the Move with move/buttons_test.py.)

## Console mode (no RNBO)
RNBO's manager (`rnbomovecontrol`) unplugs anyone else from the screen and pads, so we replace it.
`RNBOLauncher` here is a modified copy of `/data/UserData/rnbo/bin/RNBOLauncher` (original kept on the Move as
`RNBOLauncher.orig`). If `/data/UserData/console/ENABLED` exists, choosing RNBO in the Move's settings
(Shift + Step 2, bottom of the list) starts JACK and the Console app (log: console/app.log); when the app ends
(Shift + Back) the launcher stops and the Move goes back to normal. Also `touch /data/UserData/console/STOP` ends it and
the Move goes back to normal (the app's Shift + Back does this too, after saving). `rm /data/UserData/console/ENABLED` brings RNBO back.

Our programs can't get real-time priority or lock memory (warnings at start); so far that has been fine
(345 audio cycles a second, no dropouts heard).

## Files
- `move_test.py` — hardware test: tone per pad, pad lights, screen text, prints every control message.
  `python3 /data/UserData/move_test.py`
- `RNBOLauncher` — the launcher above. `move-update.py` installs changes to it (once the original is saved as .orig).
- `screen_mockups.py` / `screen-mockups.png` — first screen design proposal (recorder, drum list, drum knob turn).

## The C sound core (pi-app/core)
`core.c` is a JACK client whose process callback makes the sound, 128 frames at a time: instruments (as
"sources"), effects, the Move's controls in, lights and screen out. Python (`core.py`, `instruments.py`) sets
it up and sends timed events; it never runs in the audio path. Measured on the Move: LXR + Dexed + Plaits +
Braids jamming = 8-9% JACK load (the Python engine needed ~61% for the same). Pads feel immediate.
Events can arrive in any order (steps sent ~100 ms ahead, pad hits for now): the core sorts them by frame.
Tests: `move/core_test.py` (pads), `move/seq_test.py` (the real sequencer; `quiet` = pads only).

## Updating
- From the Mac, in one go: `bash ~/update-move.sh` (Pi builds, Mac copies, Move unpacks).
- On the Move itself: `python3 /data/UserData/console/move/move-update.py` downloads the latest from GitHub and
  builds the sound core and effects with Zig (installed once with `... move-update.py setup` into
  /data/UserData/zig). Needs a GitHub fine-grained access key, read-only "Contents" on console-move only,
  saved in /data/UserData/console/github-token. It also installs numpy/Pillow (pip --user) if missing and downloads
  the synths, drum machines and other libraries that GitHub builds (`.github/workflows/move-libs.yml`, the
  "libs-latest" release; Actions > Build Move libraries > Run workflow to rebuild by hand, 1-3 hours).
- After a factory restore: install RNBO, `mkdir -p /data/UserData/console`, save the token in
  `console/github-token`, fetch `move/move-update.py` (see below), then run it. No Pi needed.

## The app's controls (move/app.py)
- Left buttons, top to bottom: 1 instruments (again: the drum's sound, again: its sequencer); 2 song mode
  (move/movesong.py); 3 FX; 4 the recorder (the tape; again: the selected track zoomed: knob 1 mono / stereo,
  2 its input, 4-6 the box under the playhead).
- Drum pads: left 4 x 4 the drums (bottom left first), right 4 x 4 the picked drum chromatically (its TUNE /
  PITCH setting locked, SEMI clicks a semitone). Shift + pad 1-16: the instrument's pattern.
- Drum sequencer (move/moveseq.py): step buttons = 16 steps (<- / -> for 17-64), tap on / off; knobs 1 length,
  2 rate, 3 euclid, 4 shift; + / - the pads' octave (patterns: Shift + a pad). Shift + tap steps: select them; the pads are then their step
  settings (OP-XY style: velocity, chance, multiply, pulse, hold, jump, random, ramp up / down, then the drum's
  sound locks); tap a pad = on (knob 1 sets it), again = off; tap a step = done. Pulse / hold / jump / pitch
  play in pi-app/sequencer.py (Step.comp, _path / _slot).
- Tracks: step buttons select (white); Shift + step arms (red; both: blinking). Record only records armed tracks
  (engine.select_arms = False, engine.record_tracks()); the selected track still takes Copy / Cut / Splice.
- Sound pages: Up / Down (CC 55 / 54) = the pads' octave (T.octave, -4..+4), Left / Right = settings pages.
- Knobs on settings that pick a mode (DIST, CHOKE, a wave, on / off): 5 clicks the same way per choice (move/knobgate.py;
  Shift + turn: one a click).
- Knob speed (global): every number knob 1-8 needs knobgate.SPEED raw clicks per step (default 3, 1-12), saved in
  /data/UserData/console/knob-sensitivity; Shift + volume knob changes it (or edit the file). Wheel, +/- and menus aren't slowed.
- Song mode: rows of a pattern per instrument and a repeat count; step buttons = rows, knobs 1-7 patterns,
  8 repeats, + on / - off (Shift + left button 2: on / off from any page; the instruments play on the song page). Saved in data/songmode/<song>.json.
- Menu: the project menu (SETTINGS > SOFTWARE UPDATE: move/moveupdater.py runs move-update.py, then the app
  exits with 75 and RNBOLauncher starts it again). Shift + Menu: export.
- Shift + Back: save, quit and hand the Move back.

## Big screen (move/screenview.py, screenview.html)

http://move.local:8080 on a phone / tablet on the same network (or the Move on the phone's hotspot): the tape
with real waveforms, 8 tracks, bar grid, loop, track states, and a copy of the Move's screen. View only. The
page polls /state (~15 a second) and fetches /wave/<channel>:<crc> only when a waveform changes. Sized for
a Galaxy Z Fold's open screen (2448 x 1848 landscape); "Full screen" button, or Chrome > Add to home screen.

## Crash logs (move/crashlog.py)

Every run writes console/crashes/running.log: what the app prints, every button / knob / pad, and (with
faulthandler) the Python line of a crash inside an effect or synth; if the main loop stops for 20 s, every
thread's line too (a freeze). A normal quit deletes it. Found at the next start: it's kept as
crashes/crash-<date>.log (the last 20) and the screen says so. So after a crash, any time later:

    ssh -i ~/.ssh/move_key ableton@move.local "cd /data/UserData/console/crashes; ls; tail -150 running.log"     # just crashed (Console not started again)
    ssh -i ~/.ssh/move_key ableton@move.local "cd /data/UserData/console/crashes; tail -150 \$(ls -t crash-*.log | head -n 1)"   # later

## Stress test (move/stress.py)

    ssh -i ~/.ssh/move_key ableton@move.local "echo 60 > /data/UserData/console/stress"

(minutes; "60 random" skips parts 1-2). A running Console restarts into it. Its own data (console/stress-data),
so your songs aren't touched. 1: every instrument loaded and played (memory each takes); 2: every insert effect
(with a second beside it) on a playing synth; 3: random presses ~10/s plus a random instrument / insert /
save / open / new project every 12-30 s; every 8 min an empty project's memory (they should stay level).
Memory every 30 s, sudden jumps (+40 MB) with the actions just before. Report: console/stress-report.txt.
At the end Console restarts as normal. A crash: the report says so at the next start, crash in crashes/.

## Step icon test
The icons printed under the 16 step buttons are lights of their own (controller numbers 16-31, channel 16, the value
is the colour: 120 white, 118 light grey). To see which icon is which: `touch /data/UserData/console/icontest`
lights one, and the jog wheel steps to the next (the screen says which step button it is under); `echo all > ...icontest` lights all 16;
`rm /data/UserData/console/icontest` ends it. (Octave on the original Move OS: the Up / Down buttons, CC 55 / 54.)
- Choosing an instrument (instruments page, push on a slot): one picture at a time, the wheel slides left / right
  (move/pages.py carousel). Pictures are move/instimg/<module id>.txt (64 rows x 32 hex digits, from the screen
  designer's PIXELS); an instrument without one shows its name in a frame. Have: hush1, 808, 606, braids, dexed, obxd.
- NUDGE step component (pad after RAMP DOWN): a step plays up to 50% of a step early or late (-50..+50% in 10s; sequencer.py "nudge").
- Synth sequencer (move/movesynth.py, over pi-app/notes.py): step buttons = steps (tap: notes on / off; hold + pads: add / remove
  notes; hold + a later step: the length; Shift + steps: select, pads = settings, knob 1 sets). Two types per track (knob 3):
  UNIFIED or PER NOTE (tap a pad: its steps only). Record button on a drum or synth sequencer page: live record into the
  pattern (T.live_rec), not the tape; right-hand drum pads record their pitch as a step lock.
- SAMPLER (pi-app/sampler.py + drums/sampler/sampler.c, built by build-for-move.sh): 16 drums, each a .wav from the Move's sample
  folders (/data/UserData/UserLibrary/Samples, /data/UserData/console/samples, or CONSOLE_SAMPLES=dir:dir). Per drum: SAMPLE (push the big wheel: a folder browser), LEVEL,
  PITCH, START, DECAY, PAN, REVERB, DELAY. Songs keep a sample as its place in the sorted file list.
- The Move's audio input (guitar, mic: system:capture_1/2) is a tape input: INPUT L / INPUT R (core channels EXT_IN = 88, 89),
  chosen in the zoomed track view (knobs 1-3) after the instrument channels. A track armed on it hears it while you play
  (core_ext_monitor). Mono: INPUT L or R; stereo: pick both sides. Needs the new libconsolecore.so (GitHub build).
- LFOs (pi-app/lfo.py, move/movelfo.py): every instrument has 2, aimed at one of its number settings (DEST, WAVE, SPEED in note
  values, DEPTH, PHASE, MODE FREE/TRIG). Pages after the last sound page (Right past it). Kept per pattern; a never-used pattern
  starts as a copy of the one you came from. The Runner (core bridge tick) sends the moved value without changing the value on
  the page. Not done yet: LFO step sequencer / parameter locks.
- Ready-made Schwung modules (catalog.py entries with "asset", and FX_ASSETS for effects): build.py downloads each one's release
  .tar.gz (Schwung's own Move build) into schwung/modules/<id>/ when the libraries are built (GitHub Actions), so they arrive with
  the update and have pictures (move/instimg/<id>.txt). There is no in-app store any more. To add one: add an entry (id, title,
  repo, asset name from Schwung's module-catalog.json), draw a picture, push.

## INSERT effects (two per instrument, 36 effects)
36 prebuilt Schwung effects come with the update (catalog.FX_ASSETS), each with a picture in move/fximg/<id>.txt (plus none.txt). Each instrument (slot) has two inserts in series. They are the last two pages of its sound pages (settings pages → LFO 1 → LFO 2 → INSERT 1 → INSERT 2, with the wheel or the arrows); the FX key (left button 3) is only REVERB → DELAY. On an insert page push the wheel for the picture picker (turn = browse, push = choose, Back = cancel); knobs 1-8 are the effect's first eight settings (saved per slot in insert-fx.json as slots/<slot>/<pos>). They run in the core (core_slot_insert) on the slot's direct sound, before the slot's own reverb/delay and before the tape can record it, so the tape's KIT inputs have them and nothing is applied to the tape afterwards. (Per-drum inputs 1-8 stay dry.) Every Ducker of another slot gets a note whenever drum 1 (lane 1) is hit by a pad or any sequencer. CPU with many heavy effects is unmeasured.

## INSERT effect (Tapescam, Ducker...)
Tapescam and Ducker come with the update (catalog.FX_ASSETS). FX key cycles REVERB → DELAY → INSERT. On INSERT: knob 1 picks the effect, knobs 2-4 its first three settings. It runs on the whole output (not on the tape tracks), and your choice is remembered. The Ducker gets a note whenever drum 1 (lane 1) is hit by a pad or the sequencer (the sequencer one only for the instrument you're looking at).
Needs the new libconsolecore.so + libschwunghost.so (GitHub build, then update).

## Newer features (this round)
- **Synth steps:** NUDGE (a step early/late) joins LENGTH/VELOCITY/CHANCE/MULTIPLY. A note you record live lasts as long as you hold the pad.
- **LFO steps:** on an LFO page the 16 step buttons are the LFO's steps (1/16 notes, one bar). Tap = that step rests; hold a step + knob 2 = its own WAVE, knob 4 = its own DEPTH.
- **Chromatic drum pads by hand:** on a drum sequencer, hold a step button and press a right-half pad: the step turns on with that pitch.
- **Ableton Link:** MENU > SETTINGS > MIDI SYNC > LINK. Tempo is shared while stopped (a running tape keeps its tempo), PLAY/STOP are shared and start on the next bar. Needs the new libs (Link is built in the cloud like the rest).
- **Synth step settings = the drums' set:** PULSE, HOLD, JUMP (PER NOTE type only: each pitch is its own row), RANDOM / RAMP UP / RAMP DOWN pitch and NUDGE (both types; in UNIFIED a chord moves together). The type (lane page, knob 3) can be switched any time; nothing is lost.
- **Length lights:** turning a LENGTH knob (drum lane, synth pattern, or a PER NOTE lane) lights that many step buttons purple for about a second.

## Step icons (which is under which step button)
1 folded square, 2 hexagon, 3 branching nodes (ARP), 4 arch, 5 clock, 6 two dots, 7 wavy lines, 8 grid box, 9 note with a flag,
10 note with lines, 11 circle with waves, 12 staggered lines, 13 sparkle, 14 plus with a square, 15 copy, 16 bars with a box.
Icons light only while Shift is held, on a synth's sound pages; Shift + step 2 or 3 opens them (the same again, or Back, returns to the settings pages). Hexagon (2): the PADS page (key, scale, octave, pad velocity, pad curve) on a synth.

## Arpeggiator (synths)
`pi-app/arp.py`; settings in the synth sequencer's `arp_cfg` (saved with the instrument). It sits between the notes and the
synth: the pads you hold (live) and the sequencer's chords become runs of single notes (core/instruments.py, `Slot`). Pads
are recorded as played (not the arp's notes). Page: the last sound page of a synth (Right past INSERT 2), or the icon (step 3)
on the settings pages. Knobs 1-7: ON, MODE, OCT, RATE, GATE, HOLD, STYLE (5 rhythm patterns); ARP 2: GLIDE, BEND; step buttons: the 16-step rhythm (tap:
note, accent, rest). GLIDE sends CC 65 / CC 5 (the synth must answer them); BEND is pitch bend (the synth's own range).

## Open question: OB-Xd sometimes ~18% heavier (Nov 2026, parked)
Start-up checks (`echo startup > console/stress`) with LXR-02, 606, Braids and OB-Xd playing: the sound load is
either ~45% or ~27%, and which one flips each time OB-Xd is loaded (heavy, light, heavy...). Ruled out: its
settings (identical), stuck notes (all notes off changed nothing), loading while stopped vs playing, pressing Play.
It sounds fine either way and never dropped out, so it was parked. A next step would be timing each source
(sequencer copy / hands copy) inside core.c, and checking whether the denormal flush gets switched off.
Song inserts are settled: Tape Echo 2, Dissolver, Dragonfly Hall and Cloudseed are off the SONG INSERT list
(insertfx.SONG_SKIP); with 8 playing instruments nothing else overloaded. The tape is 5 minutes long: the load
tests rewind and play on when it ends.
