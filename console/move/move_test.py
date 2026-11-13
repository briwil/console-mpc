"""Console-on-Move hardware test.

Plays a tone while you hold a pad, lights the pad, writes text on the screen,
and prints every control message (pads, buttons, knobs) in the terminal.
Runs on the Move while RNBO Takeover is active. Ctrl+C quits and gives the
screen, pads and speakers back to RNBO.

    python3 move_test.py            (screen packed as 8 rows of 8-pixel strips)
    python3 move_test.py rows       (try this if the screen looks scrambled)
"""
import ctypes as c
import math
import sys
import time

LAYOUT = sys.argv[1] if len(sys.argv) > 1 else "pages"
J = c.CDLL("/data/UserData/rnbo/lib/libjack.so.0")

# ---------------------------------------------------------------- libjack bindings
AUDIO, MIDI = b"32 bit float mono audio", b"8 bit raw midi"
IS_INPUT, IS_OUTPUT = 1, 2

class MidiEvent(c.Structure):
    _fields_ = [("time", c.c_uint32), ("size", c.c_size_t), ("buffer", c.POINTER(c.c_ubyte))]

PROCESS = c.CFUNCTYPE(c.c_int, c.c_uint32, c.c_void_p)
J.jack_client_open.restype = c.c_void_p
J.jack_port_register.restype = c.c_void_p
J.jack_port_register.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_ulong, c.c_ulong]
J.jack_set_process_callback.argtypes = [c.c_void_p, PROCESS, c.c_void_p]
J.jack_activate.argtypes = J.jack_deactivate.argtypes = J.jack_client_close.argtypes = [c.c_void_p]
J.jack_port_get_buffer.restype = c.c_void_p
J.jack_port_get_buffer.argtypes = [c.c_void_p, c.c_uint32]
J.jack_midi_get_event_count.argtypes = [c.c_void_p]
J.jack_midi_event_get.argtypes = [c.POINTER(MidiEvent), c.c_void_p, c.c_uint32]
J.jack_midi_clear_buffer.argtypes = [c.c_void_p]
J.jack_midi_event_write.argtypes = [c.c_void_p, c.c_uint32, c.c_char_p, c.c_size_t]
J.jack_connect.argtypes = J.jack_disconnect.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p]
J.jack_port_by_name.restype = c.c_void_p
J.jack_port_by_name.argtypes = [c.c_void_p, c.c_char_p]
J.jack_port_get_all_connections.restype = c.POINTER(c.c_char_p)
J.jack_port_get_all_connections.argtypes = [c.c_void_p, c.c_void_p]
J.jack_get_sample_rate.argtypes = [c.c_void_p]

status = c.c_int()
client = J.jack_client_open(b"consoletest", 1, c.byref(status))
if not client:
    sys.exit("Could not connect to JACK. Is RNBO Takeover running?")
RATE = J.jack_get_sample_rate(client)

def port(name, kind, flags):
    p = J.jack_port_register(client, name, kind, flags, 0)
    assert p, name
    return p

out_l = port(b"out_L", AUDIO, IS_OUTPUT)
out_r = port(b"out_R", AUDIO, IS_OUTPUT)
ctl_in = port(b"controls_in", MIDI, IS_INPUT)
led_out = port(b"lights_out", MIDI, IS_OUTPUT)
disp_out = port(b"display_out", MIDI, IS_OUTPUT)

# ---------------------------------------------------------------- the screen (128 x 64, 1 bit)
FONT = {  # 5x7, one byte per column, bit 0 = top row
    "A": (0x7C, 0x12, 0x11, 0x12, 0x7C), "B": (0x7F, 0x49, 0x49, 0x49, 0x36), "C": (0x3E, 0x41, 0x41, 0x41, 0x22),
    "D": (0x7F, 0x41, 0x41, 0x22, 0x1C), "E": (0x7F, 0x49, 0x49, 0x49, 0x41), "F": (0x7F, 0x09, 0x09, 0x09, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x7A), "H": (0x7F, 0x08, 0x08, 0x08, 0x7F), "I": (0x00, 0x41, 0x7F, 0x41, 0x00),
    "J": (0x20, 0x40, 0x41, 0x3F, 0x01), "K": (0x7F, 0x08, 0x14, 0x22, 0x41), "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F), "N": (0x7F, 0x04, 0x08, 0x10, 0x7F), "O": (0x3E, 0x41, 0x41, 0x41, 0x3E),
    "P": (0x7F, 0x09, 0x09, 0x09, 0x06), "Q": (0x3E, 0x41, 0x51, 0x21, 0x5E), "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31), "T": (0x01, 0x01, 0x7F, 0x01, 0x01), "U": (0x3F, 0x40, 0x40, 0x40, 0x3F),
    "V": (0x1F, 0x20, 0x40, 0x20, 0x1F), "W": (0x3F, 0x40, 0x38, 0x40, 0x3F), "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x07, 0x08, 0x70, 0x08, 0x07), "Z": (0x61, 0x51, 0x49, 0x45, 0x43),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E), "1": (0x00, 0x42, 0x7F, 0x40, 0x00), "2": (0x42, 0x61, 0x51, 0x49, 0x46),
    "3": (0x21, 0x41, 0x45, 0x4B, 0x31), "4": (0x18, 0x14, 0x12, 0x7F, 0x10), "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30), "7": (0x01, 0x71, 0x09, 0x05, 0x03), "8": (0x36, 0x49, 0x49, 0x49, 0x36),
    "9": (0x06, 0x49, 0x49, 0x29, 0x1E), ":": (0x00, 0x36, 0x36, 0x00, 0x00), "-": (0x08, 0x08, 0x08, 0x08, 0x08),
    "+": (0x08, 0x08, 0x3E, 0x08, 0x08), " ": (0, 0, 0, 0, 0),
}

def render(lines):
    px = [[0] * 128 for _ in range(64)]
    for x in range(128):                         # a frame round the edge
        px[0][x] = px[63][x] = 1
    for y in range(64):
        px[y][0] = px[y][127] = 1
    for n, text in enumerate(lines):
        x0, y0 = 4, 4 + n * 12
        for k, ch in enumerate(text.upper()[:20]):
            for col, bits in enumerate(FONT.get(ch, FONT[" "])):
                for row in range(7):
                    if bits >> row & 1:
                        px[y0 + row][x0 + k * 6 + col] = 1
    out = bytearray(1024)
    if LAYOUT == "rows":                         # 64 rows of 16 bytes, leftmost pixel = top bit
        for y in range(64):
            for x in range(128):
                if px[y][x]:
                    out[y * 16 + x // 8] |= 0x80 >> (x % 8)
    else:                                        # 8 strips of 128 bytes, each byte 8 pixels down
        for y in range(64):
            for x in range(128):
                if px[y][x]:
                    out[(y // 8) * 128 + x] |= 1 << (y % 8)
    return b"MOVEDISP" + bytes(out)

# ---------------------------------------------------------------- shared state
state = {"cycles": 0, "events": 0, "freq": 0.0, "amp": 0.0, "target": 0.0, "phase": 0.0,
         "screen": None, "lights": [], "log": []}
held = []                                        # pad notes held, most recent last

def set_screen(*lines):
    state["screen"] = render(lines)

# ---------------------------------------------------------------- the audio callback
ev = MidiEvent()

@PROCESS
def process(nframes, arg):
    state["cycles"] += 1
    # incoming pads / buttons / knobs
    buf = J.jack_port_get_buffer(ctl_in, nframes)
    for i in range(J.jack_midi_get_event_count(buf)):
        J.jack_midi_event_get(c.byref(ev), buf, i)
        msg = bytes(ev.buffer[k] for k in range(ev.size))
        state["events"] += 1
        state["log"].append(msg)
        if len(msg) == 3 and msg[0] & 0xF0 in (0x80, 0x90):
            note, vel = msg[1], msg[2] if msg[0] & 0xF0 == 0x90 else 0
            if vel:
                if note not in held:
                    held.append(note)
                state["lights"].append(bytes((0x9F, note, 127)))
            else:
                if note in held:
                    held.remove(note)
                state["lights"].append(bytes((0x9F, note, 0)))
            if held:
                state["freq"] = 440.0 * 2 ** ((held[-1] - 69) / 12)
                state["target"] = 0.2
            else:
                state["target"] = 0.0
    # pad lights
    lb = J.jack_port_get_buffer(led_out, nframes)
    J.jack_midi_clear_buffer(lb)
    while state["lights"]:
        m = state["lights"].pop(0)
        J.jack_midi_event_write(lb, 0, m, len(m))
    # screen
    db = J.jack_port_get_buffer(disp_out, nframes)
    J.jack_midi_clear_buffer(db)
    scr = state["screen"]
    if scr is not None:
        state["screen"] = None
        J.jack_midi_event_write(db, 0, scr, len(scr))
    # the tone
    left = c.cast(J.jack_port_get_buffer(out_l, nframes), c.POINTER(c.c_float))
    right = c.cast(J.jack_port_get_buffer(out_r, nframes), c.POINTER(c.c_float))
    ph, inc, amp, tgt = state["phase"], 2 * math.pi * state["freq"] / RATE, state["amp"], state["target"]
    for i in range(nframes):
        amp += (tgt - amp) * 0.002                # soft start and stop, no clicks
        v = math.sin(ph) * amp
        left[i] = right[i] = v
        ph += inc
    state["phase"], state["amp"] = ph % (2 * math.pi), amp
    return 0

J.jack_set_process_callback(client, process, None)

# ---------------------------------------------------------------- take over the hardware ports
TAKE = [b"system:playback_1", b"system:playback_2", b"system:display",
        b"system:midi_playback", b"system:midi_capture"]
saved = []                                       # (source, destination) pairs to put back

def connections(name):
    p = J.jack_port_by_name(client, name)
    lst = J.jack_port_get_all_connections(client, p) if p else None
    out, i = [], 0
    while lst and lst[i]:
        out.append(lst[i]); i += 1
    return out

for name in TAKE:
    for other in connections(name):
        src, dst = (name, other) if name == b"system:midi_capture" else (other, name)
        saved.append((src, dst))
        J.jack_disconnect(client, src, dst)

J.jack_activate(client)
me = b"consoletest:"
for src, dst in ((me + b"out_L", b"system:playback_1"), (me + b"out_R", b"system:playback_2"),
                 (b"system:midi_capture", me + b"controls_in"), (me + b"lights_out", b"system:midi_playback"),
                 (me + b"display_out", b"system:display")):
    r = J.jack_connect(client, src, dst)
    print("connect", src.decode(), "->", dst.decode(), "ok" if r == 0 else f"FAILED ({r})")

set_screen("CONSOLE TEST", "PRESS A PAD", "", "LAYOUT " + LAYOUT.upper())
print("\nRunning. Press pads, buttons and knobs. Ctrl+C to quit.\n")

# ---------------------------------------------------------------- main loop: print what comes in
last = time.time()
try:
    while True:
        time.sleep(0.05)
        if time.time() - last > 2:
            last = time.time()
            print(f"[check] audio cycles {state['cycles']}, control messages {state['events']}")
            for nm in (b"system:midi_capture", b"system:display", b"system:playback_1"):
                print("   ", nm.decode(), "->", ", ".join(x.decode() for x in connections(nm)) or "nothing")
        # if something unplugged us, plug back in (and say so)
        for src, dst in ((b"system:midi_capture", me + b"controls_in"), (me + b"lights_out", b"system:midi_playback"),
                         (me + b"display_out", b"system:display")):
            if dst not in connections(src) and J.jack_connect(client, src, dst) == 0:
                print("re-plugged", src.decode(), "->", dst.decode())
                if dst == b"system:display":
                    set_screen("CONSOLE TEST", "PRESS A PAD", "", "LAYOUT " + LAYOUT.upper())
        while state["log"]:
            m = state["log"].pop(0)
            kind = {0x80: "note off", 0x90: "note on", 0xA0: "aftertouch", 0xB0: "CC",
                    0xD0: "pressure", 0xE0: "bend"}.get(m[0] & 0xF0, "other")
            print(kind.ljust(10), " ".join(f"{b:3d}" for b in m))
            if kind == "CC":
                v = m[2] - 128 if m[2] > 63 else m[2]
                set_screen("CONSOLE TEST", f"CC {m[1]} {'+' if v > 0 else ''}{v}", "", "LAYOUT " + LAYOUT.upper())
            elif kind in ("note on", "note off") and len(m) > 2:
                set_screen("CONSOLE TEST", f"NOTE {m[1]} VEL {m[2]}", "", "LAYOUT " + LAYOUT.upper())
except KeyboardInterrupt:
    pass
finally:
    print("\nGiving the Move back to RNBO...")
    for n in list(held):
        state["lights"].append(bytes((0x9F, n, 0)))
    state["target"] = 0.0
    set_screen()
    time.sleep(0.2)
    J.jack_deactivate(client)
    for src, dst in saved:
        J.jack_connect(client, src, dst)
    J.jack_client_close(client)
    print("Done.")
