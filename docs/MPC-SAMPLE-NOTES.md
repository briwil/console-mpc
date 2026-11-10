# Akai MPC Sample: what we found (firmware 1.3.0.12)

Everything here was measured on one MPC Sample over root SSH (Nov 2026). It may not hold on other
firmware versions or other MPC models. The MPC Sample is made by Akai Professional / inMusic Brands;
this project is not affiliated with or endorsed by them.

## Getting a shell
The stock firmware reads an `autorun` folder from the SD card and runs `autorun.sh` if `autorun.check`
matches. `autorun.check` is the SHA-256 of `autorun.json` + `autorun.sh` + a fixed firmware string. The
open-source project [orrpunk-art/mpc-sample-root-ssh](https://github.com/orrpunk-art/mpc-sample-root-ssh)
uses this to start the built-in sshd over USB (192.168.155.1, port 2222, key login only). That is how all
of this was explored. Only one autorun folder runs per card.

## The machine
- Linux 6.12.60 (PREEMPT_RT), aarch64, 2 GB RAM, BusyBox userland (no python, gcc, gdb, strace, aplay;
  `amidi`, `od` and a small BusyBox are there). Only `od -b/-x`, `head -n`, no `timeout`.
- Root filesystem is read-only and full. `/data` (1.9 GB) and `/tmp` (RAM) are writable; the SD card is
  mounted at `/media/sample`.
- The app is the systemd service `ac50.service` -> `/usr/bin/launch-ac50`, which runs the firmware tool,
  sets `ulimit -S -s 1024` and `MALLOC_ARENA_MAX=1`, then `exec setarch -R -- "/usr/bin/MPC Sample"`.
  The environment of the manager (e.g. `systemctl set-environment LD_PRELOAD=...`) is passed through.
- Stopping the app (`systemctl stop ac50.service`) frees the screen, the audio and the control surface.

## Screen
`/dev/fb0`: 320 x 240, 32 bits per pixel, stride 1280. Write whole frames with `write()` after
`lseek(fd, 0, SEEK_SET)`. Toggle `/sys/class/graphics/fb0/blank` (1 then 0) once before drawing.

## Audio
ALSA card 2 (`hw:2,0`, AK4558 over I2S): stereo, 44100 Hz, S32_LE, interleaved; the stock app uses
128-frame periods and a 384-frame buffer. Card 3 is the USB audio gadget (UAC2), card 4 the USB MIDI gadget.
`libasound` is on the device (no headers).

## Control surface
Card 0 (`/dev/snd/midiC0D0`) is the control surface, a serial port (`ttyS3`, 0xFE670000) exposed as a
MIDI device by `snd-serial-generic`. Card 1 is the MIDI DIN (`ttyS0`); `ttyS2` is the kernel console.
The stock app opens the port once for reading (with ALSA timestamp framing) and once for writing; only one
writer can have it, so stop the app first. The surface needs no start-up handshake: it sends events as soon
as you touch it. (At boot the firmware tool asks "who are you?" with a MIDI Identity Request,
`F0 7E 00 06 01 F7`, and gets an Akai reply, manufacturer 0x47.)

### Input (all plain MIDI)
| Control | Message |
|---|---|
| Pads 1-16 | channel 10: Note On / poly pressure / Note Off. Notes: 37 36 42 82 (pads 1-4, bottom row), 40 38 46 44, 48 47 45 43, 49 55 51 53 (pads 13-16, top row) |
| Buttons | channel 1: Note On 7F when pressed, Note Off when released |
| K1, K2, K3, MAIN VOLUME, FADER | channel 1: CC 0x10, 0x11, 0x12, 0x13, 0x14, absolute 0-127 |
| Main encoder turn | channel 1: CC 0x64, relative (01 = one click up, 7F = one click down) |

Button notes: SHIFT 0x31, PLAY 0x52, STOP 0x51, SEQ RECORD 0x50, SAMPLE RECORD 0x49, ERASE 0x09, SAMPLE 0x06,
SEQ 0x07, MUTE 0x2B, PAD BANK 0x23, PAD FX 0x01, KNOB FX 0x00, TAP TEMPO 0x35, B1 0x0C, B2 0x0D, B3 0x0E,
16 LEVELS 0x28, CHOP 0x4B, NOTE REPEAT 0x0B, encoder push 0x6F, PLUS 0x36, MINUS 0x37.
Two more lights are set by the stock app (0x24 and 0x4A) that we have not matched to a button yet.

### Lights
- Pads: SysEx `F0 47 7F 5C 65 00 04 <pad 0-15> <R> <G> <B> F7`, colours 0-127 per channel. Pad number is the
  index into the note list above (0 = pad 1). Confirmed: a request for red lit the pad red.
- Buttons: CC on channel 1 with the **same number as the button's note**; value 0 = off, 0x7F = on (the stock app
  also uses 1, 2 and 3 for dimmer states). After the stock app stops, all button lights are on.

## Tools in this repo
- `test/mpc_test.c`: stops the app and exercises everything above (screen, a tone per pad, pad and
  button lights, a display of every control). `test/build.sh` builds it for the device with no ARM headers or
  libraries (hand-declared libc/libasound functions and stand-in libraries to link against).
  Host test: `gcc -DHOST_TEST` simulates the hardware.
- `tools/ctllog.c`: a tiny `LD_PRELOAD` logger that records every byte the stock app sends to and receives from
  the control surface (`/tmp/ctl.log`). Used to find the protocol. Load it with
  `systemctl set-environment LD_PRELOAD=/tmp/ctllog.so` and restart `ac50.service`.
