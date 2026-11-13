# Changelog

Each version is a release on the [Releases](https://github.com/briwil/console-mpc/releases) page with `Console-MPC.zip` attached.
To update, unzip the new zip onto the SD card again (`unzip -o Console-MPC.zip -d /Volumes/<card>`), so `Console/data` (your projects) is kept.

## 1.0.0

First release of Console for the Akai MPC Sample (firmware 1.3.0).

- The 8-track recorder, drum and synth sequencers, song mode, mixer, inserts, FX and Ducker, on the Sample's own screen, pads, knobs and wheel.
- A startup menu: PAD 1 = Console, PAD 2 = the normal MPC.
- The startup menu finds the panel's MIDI port by name, so the pads work on every boot.
- No loud pop when Console starts.
- The wheel reads quick turns in the right direction (it used to read some quick left turns as right).
- The sound page's grow animation keeps real-time speed when frames run late.
- Shift + turn is no longer a one-step fine adjust; Shift keeps its other jobs.
- A manual: [consoleforthesample.com](https://consoleforthesample.com).
