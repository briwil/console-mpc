#!/usr/bin/env python3
"""Turns a Console screen recording (a folder from the card's ConsoleRecordings) into things After Effects can use.

    python3 screenrec-convert.py <recording folder> [--fps 60] [--scale 4] [--wheel-degrees 15]

Writes, into <recording folder>/ae/ :
    frames/000000.png ...     the screen as a PNG sequence at --fps (import as a PNG sequence at the same frame rate)
    audio.wav                 the sound, 24-bit, trimmed / padded so it starts exactly at the first frame
    controls.json             every control, with times in seconds from the first frame
    controls-for-ae.jsx       File > Scripts > Run Script File... with your comp open: adds a null "MPC Controls" with one
                              Slider per control, keyframed (hold keyframes, so values jump like the real control)
    preview.mp4               (only if ffmpeg is installed) the frames and the sound together, to check the sync

The sliders:
    PAD 1 ... PAD 16          velocity as a percentage while held, 0 when let go
    PAD n PRESSURE            how hard the pad is pressed: the hit's velocity at the hit, higher while you squeeze harder,
                              0 when let go (percentage; linear keyframes, so it glides between the panel's few readings)
    buttons                   1 while held, 0 when let go
    K1 K2 K3 FADER VOLUME     the knob's position as a percentage (fully left / down = 0, fully right / up = 100)
    WHEEL                     the wheel's rotation in degrees, adding up as it turns (right = more); --wheel-degrees per click
    WHEEL CLICKS              the same, as a count of clicks
Every control gets a slider (untouched ones stay at 0), so the same expressions work with any recording.

Uses only Python's standard library (ffmpeg is optional).
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib

W, H = 320, 240

# the panel's messages (docs/MPC-SAMPLE-NOTES.md)
PADNOTES = [37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53]
BUTTONS = {
    0x31: "SHIFT", 0x52: "PLAY", 0x51: "STOP", 0x50: "SEQ RECORD", 0x49: "SAMPLE RECORD", 0x09: "ERASE",
    0x06: "SAMPLE", 0x07: "SEQ", 0x2B: "MUTE", 0x23: "PAD BANK", 0x01: "PAD FX", 0x00: "KNOB FX",
    0x35: "TAP TEMPO", 0x0C: "B1", 0x0D: "B2", 0x0E: "B3", 0x28: "16 LEVELS", 0x4B: "CHOP",
    0x0B: "NOTE REPEAT", 0x6F: "WHEEL PUSH", 0x36: "PLUS", 0x37: "MINUS", 0x24: "SAMPLE SELECT", 0x4A: "LOOP",
}
KNOBS = {0x10: "K1", 0x11: "K2", 0x12: "K3", 0x13: "VOLUME", 0x14: "FADER"}
WHEEL_CC = 0x64


# ---------------------------------------------------------------- reading the recording

def read_frames(path):
    """[(time_ns, rgb bytes of the whole screen)], each a full frame (the file only holds what changed)."""
    data = open(path, "rb").read()
    if data[:4] != b"CVR1":
        sys.exit("%s is not a screen recording" % path)
    w, h = struct.unpack_from("<HH", data, 4)
    if (w, h) != (W, H):
        sys.exit("unexpected screen size %dx%d" % (w, h))
    pos, cur, out = 8, bytearray(W * H * 3), []
    while pos + 13 <= len(data):
        if data[pos:pos + 1] != b"F":
            break
        t, runs = struct.unpack_from("<qI", data, pos + 1)
        pos += 13
        ok = True
        for _ in range(runs):
            if pos + 8 > len(data):
                ok = False
                break
            start, n = struct.unpack_from("<II", data, pos)
            pos += 8
            if pos + n * 3 > len(data) or (start + n) * 3 > len(cur):
                ok = False
                break
            cur[start * 3:(start + n) * 3] = data[pos:pos + n * 3]
            pos += n * 3
        if not ok:
            break                                   # (the end of a recording that was cut off)
        out.append((t, bytes(cur)))
    return out


def read_controls(path, wheel_degrees):
    """{name: [(time_ns, value)]}"""
    tracks = {}

    def put(name, t, v):
        tracks.setdefault(name, []).append((t, v))

    wheel = 0
    st, d, insx = 0, [], False
    if not os.path.exists(path):
        return tracks
    for line in open(path):
        parts = line.split()
        if not parts:
            continue
        t = int(parts[0])
        for hx in parts[1:]:
            b = int(hx, 16)
            if b >= 0xF8:
                continue
            if b == 0xF0:
                insx = True
                continue
            if b == 0xF7:
                insx = False
                continue
            if b & 0x80:
                insx, st, d = False, b, []
                continue
            if insx or not st:
                continue
            d.append(b)
            need = 1 if (st & 0xF0) in (0xC0, 0xD0) else 2
            if len(d) < need:
                continue
            kind, ch, a, v = st & 0xF0, st & 15, d[0], d[1] if need == 2 else 0
            d = []
            if ch == 9 and a in PADNOTES:
                pad = "PAD %d" % (PADNOTES.index(a) + 1)
                if kind == 0x90 and v > 0:
                    put(pad, t, round(v / 127 * 100, 2))
                    put(pad + " PRESSURE", t, ("hit", round(v / 127 * 100, 2)))
                elif kind == 0x80 or (kind == 0x90 and v == 0):
                    put(pad, t, 0)
                    put(pad + " PRESSURE", t, ("off", 0))
                elif kind == 0xA0:
                    put(pad + " PRESSURE", t, ("squeeze", round(v / 127 * 100, 2)))
            elif ch == 0:
                if kind == 0x90 or kind == 0x80:
                    name = BUTTONS.get(a, "BUTTON %02X" % a)
                    put(name, t, 1 if (kind == 0x90 and v > 0) else 0)
                elif kind == 0xB0 and a in KNOBS:
                    put(KNOBS[a], t, round(v / 127 * 100, 2))
                elif kind == 0xB0 and a == WHEEL_CC:
                    wheel += v if v < 64 else v - 128          # 01 = one click right, 7F = one click left (bigger on a quick turn)
                    put("WHEEL CLICKS", t, wheel)
                    put("WHEEL", t, wheel * wheel_degrees)
                elif kind == 0xB0:
                    put("CC %02X" % a, t, v)
    return tracks


def read_timing(path):
    out = {}
    if os.path.exists(path):
        for line in open(path):
            k, _, v = line.partition(" ")
            if v.strip().isdigit():
                out[k] = int(v)
    return out


# ---------------------------------------------------------------- writing

def png(rgb, scale, path):
    rows = []
    for y in range(H):
        line = rgb[y * W * 3:(y + 1) * W * 3]
        if scale > 1:
            line = b"".join(line[x * 3:x * 3 + 3] * scale for x in range(W))
        rows.append((b"\0" + line) * scale)
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W * scale, H * scale, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


def audio(src, dst, start_ns, audio_t0):
    """float32 stereo -> 24-bit, shifted so sample 0 is the first frame."""
    data = open(src, "rb").read()
    i = data.find(b"data")
    if i < 0:
        return False
    body = data[i + 8:]
    n = len(body) // 8
    floats = struct.unpack("<%df" % (n * 2), body[:n * 8])
    shift = round((audio_t0 - start_ns) * 44100 / 1e9)       # > 0: the sound started after the first frame: silence first
    if shift >= 0:
        samples = [0.0] * (shift * 2) + list(floats)
    else:
        samples = list(floats[-shift * 2:])
    out = bytearray()
    for s in samples:
        v = int(max(-1.0, min(1.0, s)) * 8388607)
        out += struct.pack("<i", v)[:3]
    frames = len(samples) // 2
    hdr = (b"RIFF" + struct.pack("<I", 36 + len(out)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 44100 * 6, 6, 24)
           + b"data" + struct.pack("<I", len(out)))
    with open(dst, "wb") as f:
        f.write(hdr + out)
    return frames


JSX = r"""// Console screen recording -> After Effects. Made by screenrec-convert.py.
// Open the comp you want the controls in, then File > Scripts > Run Script File... and pick this file.
// Adds a null "MPC Controls" with one Slider per control. Time 0 = the first frame of the recording (put the frames there too).
// Use them in an expression, e.g. a pad highlight's Opacity:
//     thisComp.layer("MPC Controls").effect("PAD 1")("Slider") > 0 ? 100 : 0
// or a knob drawing's Rotation (K1 at 0-100 % -> -135..135 degrees):
//     linear(thisComp.layer("MPC Controls").effect("K1")("Slider"), 0, 100, -135, 135)
// or the wheel:  thisComp.layer("MPC Controls").effect("WHEEL")("Slider")
(function () {
    var DATA = __DATA__;
    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) { alert("Open (click into) a composition first."); return; }
    app.beginUndoGroup("MPC Controls");
    var nul = comp.layers.addNull(comp.duration);
    nul.name = "MPC Controls";
    nul.startTime = 0;
    var fx = nul.property("ADBE Effect Parade");
    for (var i = 0; i < DATA.order.length; i++) {
        var name = DATA.order[i];
        var keys = DATA.controls[name];
        var s = fx.addProperty("ADBE Slider Control");
        s.name = name;
        var p = s.property(1);
        var times = [], vals = [];
        if (!keys.length) { p.setValue(DATA.start[name]); continue; }     // (not touched in this recording: stays 0, no keyframes)
        if (keys[0][0] > 0) { times.push(0); vals.push(DATA.start[name]); }
        for (var k = 0; k < keys.length; k++) { times.push(keys[k][0]); vals.push(keys[k][1]); }
        p.setValuesAtTimes(times, vals);
        var how = name.indexOf("PRESSURE") >= 0 ? KeyframeInterpolationType.LINEAR : KeyframeInterpolationType.HOLD;   // pressure glides between readings (the panel only sends a few)
        for (var k2 = 1; k2 <= p.numKeys; k2++) p.setInterpolationTypeAtKey(k2, how, how);
    }
    app.endUndoGroup();
    alert("Added " + DATA.order.length + " controls to \"MPC Controls\".");
})();
"""


def pressure_keys(events, t0, fps):
    """A pad's pressure as one curve: up to the hit's velocity at the hit, higher while it is squeezed harder (never below
    the hit while held), back to 0 when let go. Linear keyframes, with a key a frame before each change so the curve
    stays flat while held and doesn't creep from one hit to the next."""
    one = 1.0 / fps
    keys, level, base, held = [], 0.0, 0.0, False

    def add(sec, v):
        sec = round(max(0.0, sec), 4)
        while keys and keys[-1][0] >= sec:               # (several at one moment: the last one counts)
            keys.pop()
        keys.append((sec, v))

    for t, (what, v) in events:
        sec = (t - t0) / 1e9
        if what == "hit":
            add(sec - one, 0)
            level, base, held = v, v, True
            add(sec, level)
        elif what == "squeeze" and held:
            new = max(v, base)                             # (a plain hit reads 0 here: the hit's own strength stays)
            if new != level:
                add(sec - one / 2, level)
                level = new
                add(sec, level)
        elif what == "off" and held:
            add(sec - one, level)
            level, held = 0.0, False
            add(sec, 0)
    return keys


def every_control():
    """The sliders, in the order they're added: pads, pad pressures, knobs, the wheel, then the buttons."""
    return (["PAD %d" % i for i in range(1, 17)] + ["PAD %d PRESSURE" % i for i in range(1, 17)]
            + list(KNOBS.values()) + ["WHEEL", "WHEEL CLICKS"] + list(BUTTONS.values()))


def order_key(name):
    every = every_control()
    return (0, every.index(name), "") if name in every else (1, 0, name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--fps", type=float, default=60)
    ap.add_argument("--scale", type=int, default=4, help="pixel size of the PNGs (4 = 1280x960, sharp pixels)")
    ap.add_argument("--wheel-degrees", type=float, default=15, help="degrees per wheel click (default 15)")
    a = ap.parse_args()
    src = a.folder
    out = os.path.join(src, "ae")
    frames = read_frames(os.path.join(src, "screen.cvr"))
    if not frames:
        sys.exit("no frames in the recording")
    timing = read_timing(os.path.join(src, "timing.txt"))
    t0 = frames[0][0]
    controls = read_controls(os.path.join(src, "controls.txt"), a.wheel_degrees)
    a_frames = timing.get("audio_frames", 0)
    end = frames[-1][0]
    if timing.get("audio_start_ns") and a_frames:
        end = max(end, timing["audio_start_ns"] + int(a_frames * 1e9 / 44100))
    for keys in controls.values():
        end = max(end, keys[-1][0])
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "frames"))

    # frames: each distinct screen once as a PNG, then the sequence as links to them (fast, and takes no extra room)
    unique = os.path.join(out, "frames", ".unique")
    os.makedirs(unique)
    count = int((end - t0) / 1e9 * a.fps) + 1
    j = 0
    for n in range(count):
        t = t0 + int(n * 1e9 / a.fps)
        while j + 1 < len(frames) and frames[j + 1][0] <= t:
            j += 1
        u = os.path.join(unique, "%06d.png" % j)
        if not os.path.exists(u):
            png(frames[j][1], a.scale, u)
        dst = os.path.join(out, "frames", "%06d.png" % n)
        try:
            os.link(u, dst)
        except OSError:
            shutil.copyfile(u, dst)
        if n % 300 == 0:
            print("frames: %d / %d" % (n, count), flush=True)
    shutil.rmtree(unique)                                    # (the links keep the files)

    wav = os.path.join(src, "audio.wav")
    have_audio = False
    if os.path.exists(wav) and timing.get("audio_start_ns"):
        have_audio = bool(audio(wav, os.path.join(out, "audio.wav"), t0, timing["audio_start_ns"]))

    for name in every_control():
        controls.setdefault(name, [])                     # every control gets a slider, touched or not, so expressions always find it
    names = sorted(controls, key=order_key)
    js = {"fps": a.fps, "seconds": round((end - t0) / 1e9, 3), "order": names, "start": {}, "controls": {}}
    for name in names:
        if name.endswith(" PRESSURE"):
            js["controls"][name] = pressure_keys(controls[name], t0, a.fps)
            js["start"][name] = 0
            continue
        keys = []
        for t, v in controls[name]:
            k = round(max(0, t - t0) / 1e9, 4)
            if keys and keys[-1][0] >= k:                 # (several messages at one moment: the last one counts)
                keys[-1] = (keys[-1][0], v)
            else:
                keys.append((k, v))
        js["controls"][name] = keys
        js["start"][name] = 0
    with open(os.path.join(out, "controls.json"), "w") as f:
        json.dump(js, f, indent=1)
    with open(os.path.join(out, "controls-for-ae.jsx"), "w") as f:
        f.write(JSX.replace("__DATA__", json.dumps(js)))

    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", os.path.join(out, "frames", "%06d.png")]
        if have_audio:
            cmd += ["-i", os.path.join(out, "audio.wav"), "-c:a", "aac", "-b:a", "256k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", os.path.join(out, "preview.mp4")]
        subprocess.call(cmd)

    lost = timing.get("frames_dropped", 0), timing.get("audio_lost_frames", 0)
    print("done: %s" % out)
    print("  %d frames at %g fps (%d different screens), %s, %d controls" % (count, a.fps, len(frames),
          "sound" if have_audio else "no sound", len(names)))
    if any(lost):
        print("  note: the recorder skipped %d screen updates and %d sound frames (the card couldn't keep up)" % lost)


if __name__ == "__main__":
    main()
