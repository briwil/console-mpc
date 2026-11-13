# Drum synth

The six drum voices of the Erica Synths LXR-02, from its open-source firmware
([github.com/erica-synths/lxr-desktop-app](https://github.com/erica-synths/lxr-desktop-app)),
built for the Pi so Console can play and record them.

- `lxr/`: the LXR's sound engine, copied from the firmware's `Core/Inc` and
  `Core/Src` (only the files the drum voices need), with its `LICENSE`
  (GPL-3.0) and `NOTICE.md`. Changes: in `Src/Soundengine/DSPAudio/Oscillator.c`
  the oscillator's wrap-around test read the STM32's overflow flag with ARM
  assembly; it's the same test in plain C now. Two sound changes, also marked
  "Console change": FINE spans a semitone each way (`MidiParser.c`), and the
  snare's noise has its own volume envelope with its own decay (`Snare.c`,
  `Snare.h`; Console's parameter 247).
- `shim/`: stand-ins for the STM32 headers the engine includes (a few
  arithmetic helpers, a random number source).
- `console_drums.c`: Console's side. Starts the engine, loads the LXR's Init
  Kit, sets parameters, plays voices and hands back each voice's sound. Also
  stand-ins for the firmware parts not brought over (its sequencer, menus,
  front panel and MIDI output).
- `mod_targets.c`: the LXR's list of modulation targets (from its menu code),
  which kits refer to by number.
- `build.sh` builds `libdrums.so`. `drums.py` runs it by itself the first
  time, and again whenever these files change.

This is a modified version for Console, not official Erica Synths firmware.
