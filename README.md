# Console for the Akai MPC Sample

Work in progress: moving [Console](https://github.com/briwil/console-move) (the 8-track tape recorder with
instruments and sequencers, built for the Ableton Move) to the Akai MPC Sample.

**Status (Nov 2026):** the hardware is mapped and a test program drives it: screen, audio out, pad lights,
button lights and every control. The plan is to make the MPC "pretend to be a Move" so Console runs unchanged:
`bridge/` is a small stand-in for libjack that runs Console's real sound core on the MPC (audio out, MPC controls
as Move controls, Move lights and screen on the MPC). Passes host tests; first on-device test pending.
Python/numpy for the MPC, and a native 320x240 interface (the screen hook is `draw_move_display`), come next.
Nothing here is a release.

- What we know about the device: [docs/MPC-SAMPLE-NOTES.md](docs/MPC-SAMPLE-NOTES.md)
- Hardware test program: [test/](test/)
- Protocol logger: [tools/](tools/)
- The bridge (JACK stand-in + control mapping + demo): [bridge/](bridge/); host test: `bridge/test/run.sh`

Use at your own risk: this runs alongside the stock firmware (it doesn't change it), but a mistake can leave
the stock app stopped until you restart the MPC.

Console is free software under the GNU General Public License v3.0 ([LICENSE](LICENSE)). The 5x7 font is from Console.
"Akai Professional", "MPC" and "MPC Sample" are trademarks of inMusic Brands, Inc. This project is not affiliated
with or endorsed by Akai or inMusic.
