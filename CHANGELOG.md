# Changelog

Each version is a release on the [Releases](https://github.com/briwil/console-mpc/releases) page with `Console-MPC.zip` attached.
To update, drag the new `autorun` and `Console` folders from the zip onto the SD card and choose Replace.

## Next

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
