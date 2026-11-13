"""A big screen for Console: a web page on the Move that shows the tape properly (8 tracks with real waveforms,
the playhead, bar grid, loop points, track states), for a phone or tablet on the same network (the phone's
hotspot works anywhere):

    http://move.local:8080

It only shows: nothing on it changes Console. The page asks for the state about 15 times a second (a small
piece of JSON) and for a track's waveform only when it has changed; with no page open it costs nothing.
Made for a Galaxy Z Fold's open screen (2448 x 1848, landscape), and fits any other.
"""
import base64
import json
import os
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import popup

PORT = int(os.environ.get("CONSOLE_SCREEN_PORT", "8080"))
# this start's colour family (picked at random when Console starts): the external screen's shades, and HELLO on the pads
FAMILY = __import__("random").choice(["ORANGE", "GREEN", "YELLOW", "TEAL", "PURPLE"])
PAD_COLOUR = {"ORANGE": 3, "GREEN": 11, "YELLOW": 8, "TEAL": 15, "PURPLE": 22}      # (the Move's colour numbers)
HERE = os.path.dirname(os.path.abspath(__file__))

_T = None                 # console.Transport
_M = None                 # the project menu (a menu open: the tape view)
_frame = None             # the Move's own screen, the latest one drawn (screen.Frame)
_server = None


def start(T, menu=None):
    """Called by app.py once Console is running."""
    global _T, _M, _server
    _T, _M = T, menu
    try:
        _server = ThreadingHTTPServer(("", PORT), _Handler)
    except OSError as e:
        print("Big screen: couldn't open port %d (%s)" % (PORT, e))
        return
    _server.daemon_threads = True
    th = threading.Thread(target=_serve, daemon=True, name="big screen")
    th.start()
    print("Big screen: http://move.local:%d" % PORT)


def _serve():
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)     # below the sound and the controls
    except (AttributeError, OSError):
        pass
    _server.serve_forever(poll_interval=0.5)


_asked = 0.0              # when a page last asked (no page open: nothing is copied)


def address():
    """The big screen's address on the network the Move is on now ("" with no network)."""
    import socket
    ip = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))                 # (nothing is sent: it only picks the way out)
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    if not ip or ip.startswith("127."):
        return ""
    return "http://%s:%d" % (ip, PORT)


def frame(f):
    """app.py: the Move's screen as just drawn (for the small copy of it on the page)."""
    global _frame
    if time.monotonic() - _asked < 3:
        _frame = f.px.copy()


# ------------------------------------------------------------------ what the page gets

def _input_text(e, t):
    import pages
    src = e.inputs[t] if t < len(e.inputs) else None
    try:
        if isinstance(src, (list, tuple)):
            a, b = pages.input_parts(e, src[0]), pages.input_parts(e, src[1])
            return "%s  %s / %s" % (a[0], a[1], b[1]) if a[0] == b[0] else "%s %s / %s %s" % (a + b)
        if src == "mix":
            src = None
        a = pages.input_parts(e, src)
        return "%s  %s" % a
    except Exception:                                    # noqa: BLE001
        return ""


def _peak(e, t):
    src = e.inputs[t] if t < len(e.inputs) else None
    chans = list(src) if isinstance(src, (list, tuple)) else [src] if isinstance(src, int) else []
    try:
        return round(float(max([e.in_peaks[c] for c in chans if 0 <= c < len(e.in_peaks)] or [0.0])), 3)
    except Exception:                                    # noqa: BLE001
        return 0.0


def state():
    T = _T
    e = T.engine
    import tape
    fpb = e.frames_per_beat()
    region = e.loop_region()
    armed = set(e.record_tracks())                     # what a recording goes onto (the Move: SHIFT + a track key)
    tracks = []
    for t in range(8):
        chans = e.chans(t)
        boxes = [[round(r[0] / fpb, 4), round(r[1] / fpb, 4), int(r[2]) if len(r) > 2 and isinstance(r[2], (int, float))
                  else 0] for r in (e.regions[chans[0]] if chans else [])]
        tracks.append({
            "n": t + 1, "selected": t == T.armed - 1, "armed": t in armed, "audible": bool(e.audible(t)),
            "muted": t in e.mutes, "solo": t in e.solos, "stereo": t in e.stereo,
            "vol": round(e.volumes[t], 3), "pan": round(e.pans[t], 3), "input": _input_text(e, t),
            "peak": _peak(e, t) if (t in armed) else 0.0, "boxes": boxes,
            "waves": [_wave_id(c) for c in chans],
        })
    song = getattr(T, "song", None)
    page = _page(T)
    seq_id, seq_live = "", None
    if page == "seq":
        try:
            static, seq_live = seq_data(T)
            body = json.dumps(static, separators=(",", ":")).encode()
            seq_id = "%08x" % zlib.crc32(body)
            _seq_cache[seq_id] = body
            while len(_seq_cache) > 4:
                _seq_cache.pop(next(iter(_seq_cache)))
        except Exception as ex:                          # noqa: BLE001
            page, seq_live = "tape", {"error": str(ex)[:80]}
    auto = None
    if page == "auto":
        try:
            auto = auto_data(T)
        except Exception as ex:                          # noqa: BLE001
            page, auto = "tape", {"error": str(ex)[:80]}
    sound = None
    if page == "sound":
        try:
            sound = sound_data(T)
        except Exception as ex:                          # noqa: BLE001
            page, sound = "tape", {"error": str(ex)[:80]}
    inst = 0                                             # on an instrument page the tape view falls back to: which one
    if page == "tape":
        if getattr(T, "inst_page", False):
            inst = T.instp.row + 1
        elif (getattr(T, "drum_page", False) or getattr(T, "seq_page", False)) and e.slot is not None:
            inst = e.slot + 1
    arp_panel = None
    if page == "sound":
        try:
            if T.mlfo.arp_on_page():
                arp_panel = arp_data(T)
        except Exception as ex:                          # noqa: BLE001
            arp_panel = {"error": str(ex)[:80]}
    fx_panel = None
    if getattr(T, "fx_page", None) in ("reverb", "delay", "song1", "song2", "mixer"):
        try:
            fx_panel = fx_data(T)
        except Exception as ex:                          # noqa: BLE001
            fx_panel = {"error": str(ex)[:80]}
    try:
        menu = menu_panel(T, _M)
    except Exception as ex:                              # noqa: BLE001
        menu = {"title": "MENU", "rows": [], "hint": str(ex)[:80]}
    if menu is not None:
        inst = 0                                         # (the panel says where you are)
    out = {
        "page": page, "inst": inst, "arp": arp_panel, "fx": fx_panel, "menu": menu, "seq_id": seq_id, "seq": seq_live, "sound": sound,
        "auto": auto,
        "t": time.time(),
        "pos": round(T.tape.pos, 5), "playing": bool(T.playing), "recording": bool(T.recording),
        "overdub": e.rec_mode == "overdub", "bpm": round(e.bpm, 2),
        "sig": list(getattr(e, "time_sig", (4, 4))), "bar": tape.BEATS_PER_BAR, "unit": tape.BEAT_UNIT,
        "position": T.position_text(T.tape.pos), "length": round(e.frames / fpb, 3),
        "zoom": tape.ZOOMS[T.tape.zoom], "res": tape.RES,
        "loop": [round(region[0] / fpb, 4), round(region[1] / fpb, 4)] if region else None,
        "loop_on": bool(e.loop_on),
        "song": e.song or "", "song_mode": bool(song is not None and song.on and song.rows),
        "message": T.message if T.message and time.monotonic() < T.message_until else "",
        "popup": popup.current(T),
        "pagefx": T.pagefx.phone() if getattr(T, "pagefx", None) is not None else None,
        "tracks": tracks,
        "screen": _screen_b64(),
    }
    return out


_wave_cache = {}          # channel -> (crc, bytes)
_seq_cache = {}           # tag -> the sequencer's pattern as JSON (the page asks for it when the tag changes)


def _page(T):
    """Which view the big screen shows: the sequencer when the Move is on it, else the tape."""
    m = _M
    if m is not None and (m.open or getattr(getattr(m, "kits", None), "open", False)):
        return "tape"
    if getattr(T, "fx_page", None):
        return "tape"
    e = T.engine
    if not (e and e.drums and e.slot is not None and e.slots[e.slot]):
        return "tape"
    if getattr(T, "seq_page", False) and getattr(T, "auto", None) is not None and T.auto.active():
        return "auto"
    if getattr(T, "seq_page", False):
        return "seq"
    if getattr(T, "drum_page", False) and not getattr(T, "inst_page", False) \
            and not T.sbrowse.active:                     # (the LFO / INSERT / ARP / PADS pages are its tabs too)
        return "sound"
    return "tape"


CHOICE_KINDS = ("menu", "onoff", "voice", "vel_target", "lfo_target")


def sound_data(T):
    """The instrument's sound page: its pages, the one shown, its 8 settings (and which an LFO is moving)."""
    import lfo
    e = T.engine
    d = e.drums
    mid = e.slots[e.slot]
    try:
        import instpage
        title = dict(instpage.machines()).get(mid) or mid
    except Exception:                                    # noqa: BLE001
        title = mid
    pages = T.drum_pages()
    tab = min(T.drum_tab, len(pages) - 1)
    params = pages[tab][1][:8]
    synth = bool(e.is_synth(mid))
    lfos = T.mlfo.lfos() if hasattr(e.seq, "pattern") else []
    if lfo.per_drum(d):                                  # (a sampler: the LFOs of the drum you're on)
        b = T.mlfo.base()
        lfos = lfos[b:b + lfo.COUNT]
    last = getattr(getattr(e, "bridge", None), "_lfos", None)
    last = getattr(last, "last", {}) if last else {}
    now = time.monotonic()
    knobs = []
    for i, p in enumerate(params):
        kind = d.kind(p)
        k = {"n": i + 1, "label": d.label(p), "text": d.value_text(p), "choice": kind in CHOICE_KINDS,
             "options": 0, "at": 0,
             "frac": round(max(0.0, min(1.0, d.fraction(p))), 4),
             "turning": now - T.drumpage.edited.get(i + 1, 0.0) < 1.0}
        if k["choice"]:
            try:
                top = int(lfo.top(d, p))
                if 1 <= top < 24:
                    k["options"], k["at"] = top + 1, int(d.get_param(p))
            except Exception:                            # noqa: BLE001
                pass
        for j, l in enumerate(lfos):
            if l.get("dest") == p:
                k.setdefault("lfo", []).append(j + 1)
                v = last.get((e.slot, j))
                if v and v[0] == p:
                    try:
                        k["mod"] = round(max(0.0, min(1.0, d.fraction(p, v[1]))), 4)
                    except Exception:                    # noqa: BLE001
                        pass
        knobs.append(k)
    page_names = [n for n, _ in pages]
    out = {"title": title, "id": mid, "synth": synth, "slot": e.slot + 1, "pages": page_names, "tab": tab,
           "knobs": knobs, "octave": getattr(T, "octave", 0)}
    if not synth:
        names = list(getattr(d, "lane_names", None) or [])
        lv = list(getattr(d, "lane_voice", None) or range(len(names)))
        hits = getattr(T, "_drum_hits", [])
        voice = getattr(T, "drum_voice", 0)
        out["pads"] = [{"name": names[i], "voice": lv[i] if i < len(lv) else i,
                        "on": voice == (lv[i] if i < len(lv) else i),
                        "hit": round(now - hits[lv[i] % len(hits)], 3) if hits and i < len(lv) else 9}
                       for i in range(min(16, len(names)))]
        vn = list(getattr(d, "names", None) or [])
        out["voice"] = vn[voice] if voice < len(vn) else ""
    _extra_pages(T, out, len(page_names))
    return out


def _card(n, label, text, frac=0.0, options=0, at=0, choice=False):
    return {"n": n, "label": label, "text": text, "choice": choice, "options": options, "at": at,
            "frac": round(max(0.0, min(1.0, frac)), 4), "turning": False}


def _extra_pages(T, out, base):
    """The pages after the instrument's own (right past the last one, as on the Move): LFO 1, LFO 2, INSERT 1,
    INSERT 2, and a synth's ARP and PADS. On one of them the 8 cards are its settings."""
    import lfo
    import notes as notes_mod
    ml = T.mlfo
    inserts = ml._inserts()
    extra = ["LFO %d" % (i + 1) for i in range(lfo.COUNT)] + ["INSERT %d" % (i + 1) for i in range(inserts)]
    extra += ["SENDS"]
    extra += ["ARP", "PADS"] if ml.has_arp() else ["PADS"]
    out["pages"] = out["pages"] + extra
    if not ml.active():
        return
    if ml.sends_on_page():
        out["tab"] = base + extra.index("SENDS")
        e = T.engine
        cards = []
        for i, (label, shown) in enumerate(ml.sends_values()):
            if i < 2:
                v = e.inst_send("reverb" if i == 0 else "delay")
                frac = v if v is not None else 0.0
            else:
                sf = T.songfx(i - 2)
                frac = sf.amount(e.slot if e.slot is not None else 0) / 100.0 if sf.index else 0.0
            cards.append(_card(i + 1, label, shown, frac))
        out["knobs"] = cards
        return
    if ml.pads_on_page() and "PADS" in extra:          # (a panel goes over this, like the arp's)
        out["tab"] = base + extra.index("PADS")
        out["knobs"] = []
        seq, vals = T.engine.seq, dict(ml.pads_values())
        oc, curve = getattr(T, "octave", 0), getattr(T, "pad_curve", 1)
        feel = [{"label": "OCTAVE", "options": ["%+d" % o if o else "0" for o in range(-4, 5)], "at": oc + 4},
                {"label": "VELOCITY", "text": vals["VELOCITY"]},
                {"label": "CURVE", "options": ["SOFT", "NORMAL", "HARD"], "at": curve}]
        rows = ([{"label": "KEY", "options": list(notes_mod.NAMES), "at": seq.root},
                 {"label": "SCALE", "options": [n for n, _ in notes_mod.SCALES], "at": seq.scale}]
                if ml.has_arp() else []) + feel                 # (a drum machine: no key or scale)
        for i, r in enumerate(rows):
            r["n"] = i + 1
        out["panel"] = {"title": "PADS", "rows": rows}
        return
    if ml.arp_on_page():                                 # (the arp's own panel goes over this)
        out["tab"] = base + extra.index("ARP") if "ARP" in extra else out["tab"]
        out["knobs"] = []
        return
    pos = ml.insert_pos()
    if pos is not None:
        out["tab"] = base + lfo.COUNT + pos
        ins = T.insfx(None, pos)
        import catalog
        fid = catalog.FX[ins.index - 1]["id"] if 0 < ins.index <= len(catalog.FX) else "none"
        out["insert"] = {"name": ins.name(), "img": "fx." + fid}
        cards = []
        for i in range(8):
            label, shown = ins.text(i)
            if not label:
                continue
            key, _l, lo, hi, _d, _s, opts = ins.params[i]
            v = ins.values.get(key, 0)
            if opts:
                cards.append(_card(i + 1, label.upper(), shown, choice=True, options=len(opts), at=int(v)))
            else:
                cards.append(_card(i + 1, label.upper(), shown, (v - lo) / ((hi - lo) or 1)))
        out["knobs"] = cards
        return
    if ml.tab is not None and ml.tab < lfo.COUNT:
        out["tab"] = base + ml.tab
        l = ml.cur()
        vals = ml.values()
        out["knobs"] = [
            _card(1, "DEST", vals[0][1], choice=True),
            _card(2, "WAVE", vals[1][1], choice=True, options=len(lfo.WAVES), at=l["wave"]),
            _card(3, "SPEED", vals[2][1], choice=True, options=len(lfo.SPEEDS),
                  at=lfo.SPEED_ORDER.index(l["speed"]) if l["speed"] in lfo.SPEED_ORDER else 0),
            _card(4, "DEPTH", vals[3][1], (l["depth"] + 100) / 200.0),
            _card(5, "PHASE", vals[4][1], l["phase"] / 100.0),
            _card(6, "MODE", vals[5][1], choice=True, options=len(lfo.MODES), at=l["mode"])]


def _rows(labels, pick):
    return [{"label": str(x).upper()} for x in labels], max(0, min(len(labels) - 1, pick)) if labels else 0


def menu_panel(T, m):
    """Whatever menu or list the Move has open (the project menu, SETTINGS, the projects, naming, the instrument
    menu and its pattern items, presets, the questions, the sample browser, the effect / instrument pickers,
    the instruments list, song mode), as a panel: a title, its rows (the picked one, values on the right), a hint.
    None when there's none (the pages with their own views)."""
    import menu as menu_mod
    e = T.engine
    msg = lambda o: str(getattr(o, "msg", "") or "").upper()
    if m is not None and m.open:
        mode = getattr(m, "mode", "")
        if mode == "qr":
            return None                                  # (the code to get here: no use showing it here)
        if mode == "name":
            title = {"new": "NAME THE NEW PROJECT", "rename": "RENAME %s" % getattr(m, "renaming", ""),
                     "wifi": "PASSWORD FOR %s" % getattr(m, "joining", "")}.get(m.naming, "NAME THIS PROJECT")
            return {"title": title.upper(), "name": "".join(m.name), "cursor": m.cursor,
                    "hint": msg(m) or "WHEEL: LETTER  ·  < >: MOVE  ·  DELETE: ERASE  ·  PLAY: OK  ·  BACK: CANCEL"}
        if mode == "settings":
            names = {"TIMESIG": "TIME SIG", "SCREEN": "EXTERNAL SCREEN"}
            rows = []
            for what in menu_mod.SETTINGS:
                full = str(m.setting_text(what) or "")
                rows.append({"label": names.get(what, menu_mod.LABELS.get(what, what)).upper(),
                             "text": full.split("  ")[0].split(": ")[0].upper().strip()})
            full = str(m.setting_text(menu_mod.SETTINGS[m.row]) or "").strip()
            hint = msg(m) or (m.update_message() if menu_mod.SETTINGS[m.row] == "UPDATE" else "") or full
            return {"title": "SETTINGS", "right": "TURN, PUSH: DONE" if m.editing else "PUSH: CHANGE IT",
                    "rows": rows, "pick": m.row, "editing": bool(m.editing), "hint": str(hint).upper()}
        if mode == "load":
            if m.confirm and m.confirm[0] == "open":
                return {"title": "OPEN PROJECT", "lines": ["THIS SONG ISN'T SAVED", "OPEN " + str(m.confirm[1]).upper()],
                        "hint": "THE UNSAVED SONG IS LOST  ·  PLAY: OPEN IT ANYWAY  ·  BACK: NO, SAVE MINE FIRST"}
            if m.confirm and m.confirm[0] == "delete":
                return {"title": "DELETE PROJECT", "lines": ["ARE YOU SURE?", str(m.confirm[1]).upper()],
                        "hint": "IT IS GONE FOR GOOD  ·  PLAY: YES, DELETE IT  ·  BACK: NO, KEEP IT"}
            renaming, deleting = getattr(m, "rename_pick", False), getattr(m, "deleting", False)
            title = "RENAME WHICH PROJECT?" if renaming else "DELETE WHICH PROJECT?" if deleting else "OPEN PROJECT"
            rows, pick = _rows(m.songs, m.pick)
            for r, name in zip(rows, m.songs):
                if e and name == e.song:
                    r["text"] = "OPEN"
            hint = "PLAY: RENAME  ·  BACK: CANCEL" if renaming else "PLAY: DELETE  ·  BACK: CANCEL" if deleting \
                else "PLAY: OPEN  ·  BACK: CANCEL"
            return {"title": title, "right": str(len(m.songs)), "rows": rows, "pick": pick,
                    "empty": "NO SAVED PROJECTS", "hint": msg(m) or hint}
        if mode == "list":
            shift = bool(getattr(T, "shift_held", lambda: False)())
            labels = [{"NEW": "DELETE PROJECT" if shift else "NEW PROJECT",
                       "SAVE": "RENAME PROJECT" if shift else "SAVE PROJECT",
                       "LOAD": "LOAD PROJECT", "SETTINGS": "SETTINGS"}[k] for k, _ in menu_mod.ITEMS]
            rows, pick = _rows(labels, m.choice)
            return {"title": ((e.song or "UNTITLED") if e else "DEMO").upper(), "right": "MENU", "rows": rows,
                    "pick": pick, "hint": msg(m) or ("SHIFT + PUSH: DELETE / RENAME" if not shift else "")}
        return _text_screen(m.s, msg(m))
    if m is not None and m.kits.open:
        k = m.kits
        if k.mode == "list":
            import kitmenu
            labels = [kitmenu.TEXTS[key] for key, _ in kitmenu.ITEMS] + [kitmenu.MAIN_TEXTS[key] for key, _ in kitmenu.MAIN]
            labels = labels[1:]
            rows, pick = _rows(labels, max(0, k.choice - 1))
            return {"title": "INSTRUMENT MENU", "right": "%d/%d" % (max(1, k.choice), len(labels)),
                    "rows": rows, "pick": pick, "hint": msg(k)}
        if k.mode == "name":
            return {"title": "NAME THIS PRESET", "name": "".join(k.name), "cursor": k.cursor,
                    "hint": msg(k) or "WHEEL: LETTER  ·  < >: MOVE  ·  DELETE: ERASE  ·  PLAY: OK  ·  BACK: CANCEL"}
        if k.mode == "load":
            rows, pick = _rows(k.kits, k.pick)
            return {"title": "LOAD PRESET", "right": str(len(k.kits)), "rows": rows, "pick": pick,
                    "empty": "NO SAVED PRESETS", "hint": msg(k) or "PLAY: LOAD IT  ·  BACK: CANCEL"}
        if k.mode in ("clear_all", "clear", "paste"):
            import notes as notes_mod
            synth = isinstance(k.seq, notes_mod.NoteSequencer)
            n = k.seq.current + 1
            if k.mode == "clear_all":
                on = k.on_count()
                title, lines = "CLEAR PATTERN %d?" % n, ["%d %s ON" % (on, ("NOTE" if on == 1 else "NOTES") if synth else
                                                                     ("STEP" if on == 1 else "STEPS")),
                                                       "STEPS, LOCKS, LENGTHS, RATES: ALL BACK TO A NEW PATTERN"]
            elif k.mode == "clear":
                locks, steps = k.lock_count()
                title, lines = "CLEAR LOCKS?  PATTERN %d" % n, ["%d LOCK%s" % (locks, "" if locks == 1 else "S"),
                                                                "ON %d %s: NOTES STAY, SETTINGS RESET" % (steps, "NOTES" if synth else "STEPS")]
            else:
                title, lines = "PASTE PATTERN %d?" % (k.pattern_clip[1] + 1), ["ONTO PATTERN %d" % n,
                                                                              "IT HAS NOTES OR STEPS: PASTING REPLACES THEM"]
            return {"title": title, "lines": lines, "hint": "PLAY: YES  ·  BACK: NO, KEEP IT"}
        return _text_screen(k.s, msg(k))
    sb = getattr(T, "sbrowse", None)
    if sb is not None and sb.active:
        rows, pick = _rows([r[0] for r in sb.entries], sb.pick)
        return {"title": sb.title(), "rows": rows, "pick": pick, "empty": "EMPTY", "hint": "PUSH: CHOOSE  ·  DELETE + PUSH: REMOVE" if sb.stage == "which" else "PUSH: OPEN / CHOOSE  ·  BACK: UP"}
    fp = getattr(T, "fxpick", None)
    if fp is not None and fp.active and fp.choices and fp.editing:
        rows, pick = _rows([c[0] for c in fp.choices], fp.pick)
        return {"title": "SHOW OR HIDE EFFECTS", "rows": rows, "pick": pick,
                "hint": "WHEEL: PICK  ·  PUSH: TICK / UNTICK  ·  BACK: DONE"}
    if fp is not None and fp.active and fp.choices:
        rows, pick = _rows([c[1] for c in fp.choices], fp.pick)
        return {"title": "CHOOSE AN EFFECT", "rows": rows, "pick": pick,
                "img": "" if fp.choices[fp.pick][0] == "__edit__" else "fx." + fp.choices[fp.pick][0],
                "hint": "WHEEL: PICK  ·  PUSH: CHOOSE  ·  BACK: CANCEL"}
    if getattr(T, "inst_page", False) and not (T.drum_page or T.seq_page or T.fx_page):
        ip = T.instp
        if ip.mode == "pick" and ip.choices:
            rows, pick = _rows([c[1] for c in ip.choices], ip.pick)
            return {"title": "SLOT %d: CHOOSE AN INSTRUMENT" % (ip.row + 1), "rows": rows, "pick": pick,
                    "img": "" if ip.choices[ip.pick][0] == "__edit__" else ip.choices[ip.pick][0],
                    "hint": "WHEEL: PICK  ·  PUSH: CHOOSE  ·  BACK: CANCEL"}
        if ip.mode == "edit":
            rows, pick = _rows([c if isinstance(c, str) else c[1] for c in ip.choices], ip.pick)
            return {"title": "SHOW OR HIDE INSTRUMENTS", "rows": rows, "pick": pick,
                    "hint": "WHEEL: PICK  ·  PUSH: TICK / UNTICK  ·  BACK: DONE"}
        if ip.mode == "menu":
            rows, pick = _rows([c[1] if isinstance(c, (tuple, list)) else str(c) for c in ip.choices], ip.pick)
            return {"title": "SLOT %d" % (ip.row + 1), "rows": rows, "pick": pick}
        try:
            import instpage
            names = dict(instpage.machines())
        except Exception:                                # noqa: BLE001
            names = {}
        rows = []
        for i in range(8):
            mid = e.slots[i] if e else None
            rows.append({"label": "%d  %s" % (i + 1, (names.get(mid, mid) or "—").upper()),
                         "text": "MUTE" if (e and i in e.slot_mutes) else ""})
        return {"title": "INSTRUMENTS", "rows": rows, "pick": ip.row,
                "img": (e.slots[ip.row] if e and e.slots[ip.row] else ""),
                "hint": "PUSH: OPEN  ·  SHIFT + PUSH: CHANGE / REMOVE  ·  STEPS 1-8: MUTE"}
    if getattr(T, "song_page", False) and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        sg = T.song
        if not sg.rows:
            return {"title": "SONG " + ("ON" if sg.on else "OFF"), "right": "NO ROWS",
                    "lines": ["STEP BUTTON 1: ADD A ROW", "EACH ROW: A PATTERN FOR EVERY INSTRUMENT, PLAYED SO MANY TIMES (KNOB 8)"],
                    "hint": "+ / -: SONG MODE ON / OFF"}
        row = sg.rows[sg.pick]
        rows = []
        for i, slot in enumerate(sg.slots()):
            v = row["pats"].get(slot)
            rows.append({"n": i + 1, "label": sg.short(slot), "text": "—" if v is None else "PATTERN %d" % (v + 1)})
        rows.append({"n": 8, "label": "PLAYS", "text": "x%d" % row["repeat"]})
        playing = sg.playing_row
        return {"title": "SONG " + ("ON" if sg.on else "OFF"), "right": "ROW %d OF %d" % (sg.pick + 1, len(sg.rows)),
                "rows": rows, "pick": -1, "knobs": True, "steps": len(sg.rows), "step_at": sg.pick,
                "step_playing": playing if playing is not None else -1,
                "hint": "STEPS: ROWS  ·  DELETE + STEP: TAKE A ROW OUT  ·  + / -: SONG MODE ON / OFF"}
    return None


def _text_screen(s, msg):
    """One of the Pi's own menu screens (the tempo, Wi-Fi...): its lines, the highlighted one picked."""
    bar = s.get("menu_bar")
    bar_y = (bar["y"], bar["y"] + bar["h"]) if bar and bar.get("h") else None
    by_y = {}
    for it in s.items:
        if it.get("type") == "text" and it.get("t"):
            by_y.setdefault(int(it["y"]) // 12 * 12, []).append(it)
    lines, pick = [], 0
    for y in sorted(by_y):
        items = sorted(by_y[y], key=lambda it: it["x"])
        if bar_y and any(bar_y[0] - 4 <= it["y"] <= bar_y[1] for it in items):
            pick = len(lines)
        lines.append("  ".join(str(it["t"]) for it in items).upper())
    if not lines:
        return {"title": "MENU", "rows": [], "hint": msg}
    rows, p = _rows(lines[1:], pick - 1)
    return {"title": lines[0], "rows": rows, "pick": p, "hint": msg}


def fx_data(T):
    """Left button 3's REVERB or DELAY page, as a panel: its three settings and the picked instrument's send."""
    import effects
    e = T.engine
    which = T.fx_page
    if which == "mixer":                                     # the MIXER: the 8 instruments' volume and pan
        from console import mix_pan_text
        rows = []
        for i in range(8):
            mid = e.slots[i]
            if mid:
                rows.append({"n": i + 1, "label": T.instp.title(mid).upper()[:12],
                             "text": "MUTED" if i in e.slot_mutes else
                             "%d%%    %s" % (round(e.inst_levels[i] * 100), mix_pan_text(e.inst_pans[i]))})
        return {"title": "MIXER", "rows": rows, "hint": "KNOBS 1-8: VOLUME   SHIFT + KNOB: PAN   STEP 1-8: MUTE, SHIFT: SOLO"}
    if which in ("song1", "song2"):                          # SONG INSERT 1 / 2: the effect, its settings, its picture
        import catalog
        sf = T.songfx(0 if which == "song1" else 1)
        rows = []
        for i in range(8):
            label, shown = sf.text(i)
            if label:
                rows.append({"n": i + 1, "label": label.upper(), "text": shown})
        fid = catalog.FX[sf.index - 1]["id"] if sf.index else "none"
        return {"title": "SONG INSERT %d" % (sf.pos + 1), "right": sf.name(), "rows": rows, "pick": -1,
                "knobs": True, "img": "fx." + fid, "empty": "NO EFFECT: PUSH THE WHEEL TO CHOOSE ONE",
                "hint": (sf.error.upper() if sf.error else
                         "ON EVERY INSTRUMENT (A COPY EACH), RECORDED WITH IT  ·  PUSH THE WHEEL: CHOOSE")}
    rows = []
    for i, (key, name) in enumerate(T.FX_KNOBS[which]):
        if key == "dly_time":
            names = [n for n, _ in effects.DELAY_TIMES]
            v = e.fx[key]
            rows.append({"n": i + 1, "label": name, "options": names, "at": names.index(v) if v in names else 0})
        else:
            rows.append({"n": i + 1, "label": name, "text": T.fx_value_text(key)})
    return {"title": which.upper(), "rows": rows}


def arp_data(T):
    """The arpeggiator's settings, all of them, for the panel over the sound page: each row with its options and
    which one is picked."""
    import arp
    import sequencer
    c = T.mlfo.cfg()
    onoff = lambda v: 1 if v else 0                      # (OFF first, as the knob goes: OFF, then ON)
    rows = [
        {"n": 1, "label": "ON", "options": ["OFF", "ON"], "at": onoff(c["on"])},
        {"n": 2, "label": "MODE", "options": list(arp.MODES), "at": c["mode"]},
        {"n": 3, "label": "OCTAVE", "options": ["1", "2", "3", "4"], "at": c["oct"] - 1},
        {"n": 4, "label": "RATE", "options": [sequencer.RATES[i][0] for i in sequencer.RATE_ORDER],     # slowest to fastest, as the knob turns
         "at": sequencer.RATE_ORDER.index(c["rate"]) if c["rate"] in sequencer.RATE_ORDER else 0},
        {"n": 5, "label": "GATE", "text": "%d%%" % c["gate"]},
        {"n": 6, "label": "HOLD", "options": ["OFF", "ON"], "at": onoff(c["hold"])},
        {"n": 7, "label": "STYLE", "options": list(arp.STYLES), "at": c["style"]},
        {"n": 0, "label": "GLIDE", "text": "%d%%" % c["glide"] if c["glide"] else "OFF"},
        {"n": 0, "label": "BEND", "text": "%+d%%" % c["bend"] if c["bend"] else "OFF"},
    ]
    return {"title": "ARP", "rows": rows, "rhythm": list(c["rhythm"]), "on": bool(c["on"])}


def image(mid):
    """An instrument's picture (move/instimg/<id>.txt: 64 rows of 32 hex digits), as that text; "fx.<id>": an
    insert effect's (move/fximg)."""
    folder = "instimg"
    if mid.startswith("fx."):
        folder, mid = "fximg", mid[3:]
    try:
        return open(os.path.join(HERE, folder, "%s.txt" % os.path.basename(mid))).read().encode()
    except OSError:
        return b""


def auto_data(T):
    """The AUTOMATION page: every setting locked on some step of this pattern (the one knob 1 is on picked), with
    its value on each step; the held step; the playhead."""
    a = T.auto
    e = T.engine
    seq = e.seq
    mid = e.slots[e.slot]
    try:
        import instpage
        title = dict(instpage.machines()).get(mid) or mid
    except Exception:                                    # noqa: BLE001
        title = mid
    if T.synth_shown():
        name = ""
    else:
        names = list(getattr(e.drums, "lane_names", None) or [])
        lane = T.seqp.lane
        name = names[lane] if lane < len(names) else "LANE %d" % (lane + 1)
        if name == "EMPTY":
            name = "DRUM %d" % (lane + 1)
    keys = a.keys()
    pick = a.key()
    rows = []
    for k in keys:
        on = sorted(a.steps_with(k))
        rows.append({"label": a.label(k), "steps": {str(i): a.value_text(i, k) for i in on}})
    held = a.held
    return {"title": str(title).upper(), "name": str(name).upper(), "slot": e.slot + 1, "pattern": seq.current + 1,
            "length": a.length(pick), "rows": rows, "pick": keys.index(pick) if pick in keys else -1,
            "held": held, "held_value": a.value_text(held, pick) if (held is not None and pick is not None) else "",
            "first": a.page * 16, "at": a.playing_step(), "confirm": a.confirming(),
            "dark": bool(__import__("sequencer").TRIPLETS)}


def seq_data(T):
    """The shown instrument's pattern (what doesn't change while it plays), and what does (positions, the
    lane / steps picked)."""
    import sequencer
    e = T.engine
    seq = e.seq
    mid = e.slots[e.slot]
    try:
        import instpage
        title = dict(instpage.machines()).get(mid) or mid
    except Exception:                                    # noqa: BLE001
        title = mid
    playing = bool(e.playing)
    fpb = e.frames_per_beat()
    live = {"pattern": seq.current + 1, "queued": (seq.queued + 1) if seq.queued is not None else None,
            "rec": bool(getattr(T, "live_rec", False)),
            # (the page works the playing step out itself between updates, from these: the sequencer's clock
            # as you hear it, and where the pattern's step 0 is, in beats)
            "clock": round(e._heard_frame() / fpb, 5) if playing else None, "anchor": round(seq.anchor / fpb, 5)}
    if T.synth_shown():
        import notes
        ms = T.msyn
        pat = seq.pattern
        nl = []
        for step, d in sorted(pat.notes.items()):
            for note, n in sorted(d.items()):
                nl.append([step, note, n.length, n.vel, n.chance, n.ratchet, len(n.locks), len(n.comp)])
        shown = seq.shown_notes()
        static = {"kind": "notes", "title": title, "slot": e.slot + 1, "length": pat.length,
                  "rate": sequencer.RATES[pat.rate][0], "notes": nl,
                  "lane_len": {str(k): v for k, v in pat.lane_len.items()},
                  "root": notes.NAMES[seq.root], "scale": notes.SCALES[seq.scale][0],
                  "degrees": [(seq.root + d) % 12 for d in seq.degrees()],
                  "per_note": bool(getattr(seq, "move_type", 0)), "bar_beats": seq.bar_beats,
                  "spb": pat.steps_per_beat(), "trip": bool(seq.trip), "dark": bool(sequencer.TRIPLETS),
                  "straight": not any(n.comp for d in pat.notes.values() for n in d.values())}
        live.update({"shown": shown, "lane": ms.lane, "first": ms.first(), "page_len": ms.length(),
                     "down": sorted(ms.down), "selected": sorted(ms.selected),
                     "at": ms.playing_step() if playing else None})
        if static["per_note"]:                           # PER NOTE: a lane per note, as the drums (own length, rate)
            pitches = set(pat.lane_len) | set(pat.lane_rate) | {nt for d in pat.notes.values() for nt in d}
            if ms.lane is not None:
                pitches.add(ms.lane)
            if pitches:
                order = sorted(pitches, reverse=True)
                lanes, ats = [], []
                for pitch in order:
                    n_len = pat.lane_length(pitch)
                    steps = []
                    for i in range(n_len):
                        nt = pat.notes.get(i, {}).get(pitch)
                        steps.append([1, nt.vel, nt.chance, nt.ratchet, len(nt.locks), len(nt.comp)] if nt else [0, 0, 0, 1, 0, 0])
                    r = pat.lane_rate.get(pitch, pat.rate)
                    lanes.append({"name": notes.note_name(pitch), "length": n_len, "rate": sequencer.RATES[r][0],
                                  "spb": pat.steps_per_beat(pitch), "hits": 0, "group": sequencer.group_steps(
                                      pat.steps_per_beat(pitch), tuple(getattr(e, "time_sig", (4, 4)))),
                                  "straight": not any(st[5] for st in steps), "steps": steps})
                    at = None
                    if playing:
                        try:
                            k = seq.raw_step(e._heard_frame(), fpb, pitch)
                            at = sequencer.phys(k % (sequencer.live_len(n_len, seq.trip) or 1), seq.trip)
                        except Exception:                # noqa: BLE001
                            at = None
                    ats.append(at)
                static.update({"kind": "drums", "lanes": lanes, "chances": sequencer.CHANCES})
                live.update({"lane": order.index(ms.lane) if ms.lane in order else 0, "held": None, "at": ats})
        return static, live
    ms = T.mseq
    d = e.drums
    n = max(1, min(sequencer.MAX_LANES, getattr(d, "lanes", 8)))
    names = list(getattr(d, "lane_names", None) or [])
    lanes = []
    for li in range(n):
        ln = seq.pattern.lanes[li]
        steps = [[1 if st.on else 0, st.vel, st.chance, st.ratchet, len(st.locks), len(st.comp)]
                 for st in ln.steps[:ln.length]]
        lanes.append({"name": names[li] if li < len(names) else "LANE %d" % (li + 1), "length": ln.length,
                      "rate": sequencer.RATES[ln.rate][0], "spb": ln.steps_per_beat(), "hits": ln.hits,
                      "group": sequencer.group_steps(ln.steps_per_beat(), tuple(getattr(e, "time_sig", (4, 4)))),
                      "straight": not any(st.comp for st in ln.steps[:ln.length]),     # (plays its steps in order)
                      "steps": steps})
    static = {"kind": "drums", "title": title, "slot": e.slot + 1, "lanes": lanes, "chances": sequencer.CHANCES,
              "trip": bool(seq.trip), "dark": bool(sequencer.TRIPLETS)}
    try:
        at = seq.position(e._heard_frame(), fpb) if playing else None
    except Exception:                                    # noqa: BLE001
        at = None
    live.update({"lane": T.seqp.lane, "first": ms.first(), "held": ms.held, "selected": list(ms.selected),
                 "at": at})
    return static, live


def _wave_id(c):
    """A short tag that changes when channel c's waveform does (the page then asks for it)."""
    lv = _T.engine.levels[c] if c < len(_T.engine.levels) else None
    if lv is None:
        return "%d:0" % c
    crc = zlib.crc32(lv.tobytes())
    if _wave_cache.get(c, (None,))[0] != crc:
        v = np.clip(np.asarray(lv, np.float32), 0.0, 1.0)
        _wave_cache[c] = (crc, (v * 255).astype(np.uint8).tobytes())
    return "%d:%08x" % (c, crc)


def wave(c):
    _wave_id(c)
    return _wave_cache.get(c, (0, b""))[1]


def _screen_b64():
    f = _frame
    if f is None:
        return ""
    try:
        return base64.b64encode(np.packbits(f.astype(bool), axis=1).tobytes()).decode()
    except Exception:                                    # noqa: BLE001
        return ""


# ---------------------------------------------------------------- exports and projects, to download / back up
#   http://move.local:8080/files : every export (stems + mix) and every project, each as one ZIP or file by file

class _ZipOut:
    """A write-only stand-in for a file, so a ZIP can be streamed to the browser without a temporary copy
    (zipfile writes such a stream with data descriptors)."""
    def __init__(self, w):
        self.w, self.n = w, 0

    def write(self, b):
        self.w.write(b)
        self.n += len(b)
        return len(b)

    def flush(self):
        self.w.flush()


def _root(kind):
    if kind not in ("exports", "projects"):
        return None
    data = os.path.realpath(os.path.expanduser(os.environ.get("CONSOLE_DATA", "~/console-data")))   # (as audio.DATA)
    return os.path.join(data, kind)


def _safe(kind, *parts):
    """The path for exports/<folder>[/<file>], or None if it would leave that folder."""
    import urllib.parse
    root = _root(kind)
    if not root:
        return None
    bits = [urllib.parse.unquote(p) for p in parts]
    if any(not b or b in (".", "..") or "/" in b or "\\" in b or "\0" in b for b in bits):
        return None
    path = os.path.realpath(os.path.join(root, *bits))
    return path if path.startswith(os.path.realpath(root) + os.sep) else None


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs
               if os.path.isfile(os.path.join(d, f)))


def _mb(n):
    return "%.1f MB" % (n / 1048576.0) if n >= 104858 else "%d KB" % max(1, round(n / 1024.0))


FILES_CSS = ("body{margin:0;background:#0b0c0e;color:#e9e6df;font:16px/1.45 system-ui,-apple-system,sans-serif;"
             "padding:20px max(16px,env(safe-area-inset-left))}main{max-width:760px;margin:0 auto}"
             "h1{font-size:22px;letter-spacing:.14em;color:#f2b33d;margin:4px 0 2px}h2{font-size:13px;letter-spacing:.16em;"
             "text-transform:uppercase;color:#9b968b;margin:30px 0 8px}p.s{color:#9b968b;margin:2px 0 14px;font-size:14px}"
             "a{color:#f2b33d}.item{border:1px solid #2c2a26;border-radius:10px;padding:10px 14px;margin:8px 0;background:#141310}"
             ".row{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}"
             ".nm{font-weight:600;word-break:break-word;min-width:0}.sz{color:#9b968b;font-size:13px;margin-left:8px;font-weight:400}"
             ".btn{background:#f2b33d;color:#16110c;text-decoration:none;font-weight:700;border-radius:8px;padding:7px 14px;white-space:nowrap}"
             "details{margin-top:6px}summary{cursor:pointer;color:#9b968b;font-size:14px}"
             "ul{list-style:none;margin:6px 0 2px;padding:0}li{display:flex;justify-content:space-between;gap:10px;padding:4px 0;"
             "border-top:1px solid #1f1d19;font-size:14px;word-break:break-all}.empty{color:#9b968b}")


def files_page():
    import html
    import urllib.parse
    q = lambda s: urllib.parse.quote(s, safe="")
    out = ['<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Console files</title><style>%s</style><main><h1>CONSOLE FILES</h1>'
           '<p class="s">Download an export, or back up a project. Stop recording and playing first when you back '
           'up the project you are working on.</p>' % FILES_CSS]
    for kind, title, newest in (("exports", "Exports (stems and stereo mix)", True), ("projects", "Projects (backups)", False)):
        out.append("<h2>%s</h2>" % title)
        root = _root(kind)
        try:
            names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith(".")]
        except OSError:
            names = []
        names.sort(key=(lambda n: -os.path.getmtime(os.path.join(root, n))) if newest else str.lower)
        if not names:
            out.append('<p class="empty">Nothing here yet.</p>')
        for n in names:
            d = os.path.join(root, n)
            fl = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)) and not f.startswith("."))
            out.append('<div class="item"><div class="row"><span class="nm">%s<span class="sz">%s, %d files</span></span>'
                       '<a class="btn" href="/zip/%s/%s">Download ZIP</a></div><details><summary>Files</summary><ul>' %
                       (html.escape(n), _mb(_size(d)), len(fl), kind, q(n)))
            for f in fl:
                out.append('<li><a href="/dl/%s/%s/%s">%s</a><span class="sz">%s</span></li>' %
                           (kind, q(n), q(f), html.escape(f), _mb(os.path.getsize(os.path.join(d, f)))))
            out.append("</ul></details></div>")
    out.append("</main>")
    return "".join(out).encode()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype, cache=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=31536000" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _events(self):
        """The state pushed to the page as it changes (checked 40 times a second; sent when something did,
        and at least twice a second), instead of the page asking."""
        global _asked
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, sent = None, 0.0
        while True:
            now = time.monotonic()
            _asked = now
            try:
                st = state()
            except (RuntimeError, ValueError, KeyError, IndexError, AttributeError, TypeError):
                time.sleep(0.025)                        # (changed under it by Console: next time)
                continue
            st.pop("t", None)
            body = json.dumps(st, separators=(",", ":"))
            if body != last or now - sent > 0.5:
                self.wfile.write(b"data: " + body.encode() + b"\n\n")
                self.wfile.flush()
                last, sent = body, now
            time.sleep(0.025)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                page = open(os.path.join(HERE, "screenview.html"), "rb").read().replace(b"%%FAMILY%%", FAMILY.encode())
                self._send(page, "text/html; charset=utf-8")
            elif path in ("/files", "/files/"):
                self._send(files_page(), "text/html; charset=utf-8")
            elif path.startswith("/dl/"):
                bits = path.split("/")[2:]
                target = _safe(bits[0], *bits[1:]) if len(bits) == 3 else None
                if not target or not os.path.isfile(target):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(target)))
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(target).replace('"', ""))
                self.end_headers()
                with open(target, "rb") as fh:
                    while True:
                        chunk = fh.read(262144)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            elif path.startswith("/zip/"):
                bits = path.split("/")[2:]
                target = _safe(bits[0], *bits[1:]) if len(bits) == 2 else None
                if not target or not os.path.isdir(target):
                    self.send_error(404)
                    return
                import zipfile
                name = os.path.basename(target)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="%s.zip"' % name.replace('"', ""))
                self.end_headers()                       # (no length: the ZIP is streamed, then the connection closes)
                with zipfile.ZipFile(_ZipOut(self.wfile), "w", zipfile.ZIP_STORED, allowZip64=True) as z:
                    for d, _, fs in os.walk(target):
                        for f in sorted(fs):
                            fp = os.path.join(d, f)
                            if os.path.isfile(fp) and not f.startswith("."):
                                z.write(fp, os.path.join(name, os.path.relpath(fp, target)))
            elif path == "/manifest.json":
                self._send(json.dumps({"name": "Console", "short_name": "Console", "display": "fullscreen",
                                       "orientation": "landscape", "start_url": "/", "background_color": "#0b0c0e",
                                       "theme_color": "#0b0c0e",
                                       "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}
                                      ).encode(), "application/manifest+json")
            elif path == "/icon.svg":
                self._send(ICON.encode(), "image/svg+xml", cache=True)
            elif path == "/events":
                self._events()
            elif path == "/state":
                global _asked
                _asked = time.monotonic()
                self._send(json.dumps(state(), separators=(",", ":")).encode(), "application/json")
            elif path.startswith("/fonts/"):
                name = os.path.basename(path)
                if name.endswith(".ttf"):
                    self._send(open(os.path.join(HERE, "fonts", name), "rb").read(), "font/ttf", cache=True)
                else:
                    self.send_error(404)
            elif path.startswith("/img/"):
                self._send(image(path.split("/")[2]), "text/plain", cache=True)
            elif path.startswith("/seq/"):
                body = _seq_cache.get(path.split("/")[2])
                if body is None:
                    self.send_error(404)
                else:
                    self._send(body, "application/json", cache=True)
            elif path.startswith("/wave/"):
                c = int(path.split("/")[2].split(":")[0])
                self._send(wave(c), "application/octet-stream", cache=True)    # (its URL has the tag in it)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as ex:                          # noqa: BLE001
            try:
                self.send_error(500, str(ex)[:100])
            except Exception:                            # noqa: BLE001
                pass


ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
        'fill="#0b0c0e"/><g fill="#f2b33d"><rect x="10" y="18" width="44" height="5" rx="2"/><rect x="10" y="29" '
        'width="30" height="5" rx="2"/><rect x="10" y="40" width="38" height="5" rx="2"/></g><rect x="31" y="12" '
        'width="2" height="40" fill="#ff5a4e"/></svg>')
