# Console for the Akai MPC Sample

Work in progress: moving [Console](https://github.com/briwil/console-move) (the 8-track tape recorder with
instruments and sequencers, built for the Ableton Move) to the Akai MPC Sample.

**Status (Nov 2026):** the hardware is mapped and a test program drives it: screen, audio out, pad lights,
button lights and every control. The sound core has not been ported yet. Nothing here is a release.

- What we know about the device: [docs/MPC-SAMPLE-NOTES.md](docs/MPC-SAMPLE-NOTES.md)
- Hardware test program: [test/](test/)
- Protocol logger: [tools/](tools/)

Use at your own risk: this runs alongside the stock firmware (it doesn't change it), but a mistake can leave
the stock app stopped until you restart the MPC.

Console is free software under the GNU General Public License v3.0 ([LICENSE](LICENSE)). The 5x7 font is from Console.
"Akai Professional", "MPC" and "MPC Sample" are trademarks of inMusic Brands, Inc. This project is not affiliated
with or endorsed by Akai or inMusic.
