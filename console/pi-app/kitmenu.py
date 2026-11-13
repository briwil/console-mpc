"""The drums menu: FILE on the drum and sequencer pages.
- SAVE KIT names the drum synth's settings and keeps them; LOAD KIT puts a saved kit back. Kits live in
  ~/console-data/kits/<name>.json (the 606's and 808's in kits/606/ and kits/808/), so every song can use
  them; each drum machine lists only its own.
- DRUM MACHINE picks the song's drum machine (LXR-02, TR-606, TR-808); each has its own kit and its own
  sequencer patterns in the song, so switching back finds them as they were.
- COPY PATTERN keeps the sequencer's current pattern; PASTE PATTERN puts it onto the current one
  (go to another pattern with knob 10 in between).
- CLEAR PATTERN empties the current pattern (like a new one); CLEAR LOCKS + STEPS takes every
  parameter lock off it and puts the steps' velocity, chance and ratchets back.

The project menu's NEW, SAVE, LOAD and SETTINGS are in a second column on the right: ← / → go across,
the big knob goes down the left column and on to the top of the right one (and round again at the end).
Choosing one of those opens the project menu there; FILE from it goes back to the drums.

It looks and works like the project menu (same layout, same naming: the big knob picks the letter,
← / → move, CUT deletes, PLAY is OK, FILE goes back).
"""
import copy
import json
import os

import audio
import menu
import notes
import sequencer

KITS = os.path.join(audio.DATA, "kits")
ITEMS = [("MACHINE", "menu_more"), ("SAVE", "menu_new"), ("LOAD", "menu_save"), ("COPY", "menu_load"),
         ("PASTE", "menu_settings"), ("CLEAR_ALL", "menu_more2"), ("CLEAR", "menu_more3")]
TEXTS = {"MACHINE": "DRUM MACHINE", "SAVE": "SAVE Preset", "LOAD": "LOAD Preset", "COPY": "COPY Pattern",
         "PASTE": "PASTE Pattern", "CLEAR_ALL": "CLEAR Pattern", "CLEAR": "CLEAR Locks + Steps"}
MAIN = [("NEW", "menu_r1"), ("SAVE", "menu_r2"), ("LOAD", "menu_r3"), ("SETTINGS", "menu_r4")]   # right column
MAIN_TEXTS = {"NEW": "NEW Project", "SAVE": "SAVE Project", "LOAD": "LOAD Project", "SETTINGS": "SETTINGS"}
ALL = len(ITEMS) + len(MAIN)                 # choice 0-6: the left column; 7-10: the right
LEFT_X, RIGHT_X = 600, 700                  # the columns' inside edges
ITEM_TOP, ITEM_GAP = 84, 30                # the drums menu's 7 rows, closer together than the project menu's
ROWS = 7                                   # saved kits shown at once (the layout's set_value1-7)


def kits_dir(machine="lxr"):
    """LXR-02 kits in kits/ (as always); the 606's and 808's in kits/606/ and kits/808/."""
    return KITS if machine == "lxr" else os.path.join(KITS, machine)


def kit_names(machine="lxr"):
    try:
        files = [f[:-5] for f in os.listdir(kits_dir(machine)) if f.endswith(".json") and not f.startswith(".")]
    except OSError:
        return []
    return sorted(files, key=str.lower)


def kit_path(name, machine="lxr"):
    return os.path.join(kits_dir(machine), name + ".json")


class KitMenu(menu.Menu):
    def __init__(self, path, transport):
        super().__init__(path, transport)
        self.open = False
        self.choice = 0
        self.kits = []
        self.pick = 0                      # the kit chosen in the LOAD list
        self.replace = None                # a name that's already saved: PLAY again replaces it
        self.pattern_clip = None           # COPY PATTERN: (machine, pattern number, the pattern)
        self.machines = []                 # MACHINE: [(id, title)] to pick from
        self.main = None                   # the project menu (console.py sets it), for the right column

    @property
    def drums(self):
        e = self.engine
        return e.drums if e else None

    def show(self):
        self.open, self.mode, self.msg, self.replace = True, "list", "", None
        self.choice = min(self.choice, ALL - 1)
        self.refresh()

    # ------------------------------------------------------------ keys

    @property
    def seq(self):
        return self.engine.seq

    def key(self, name):
        if self.mode in ("load", "paste", "clear", "clear_all", "machine") and not isinstance(name, tuple):
            if name in ("UP", "LEFT", "BAR_LEFT"):
                self.turn(-1)
            elif name in ("DOWN", "RIGHT", "BAR_RIGHT"):
                self.turn(1)
            elif name in menu.CONFIRM:
                {"load": self.load, "paste": self.paste_pattern, "clear": self.clear_locks,
                 "clear_all": self.clear_pattern, "machine": self.switch_machine}[self.mode]()
            elif name == "FILE":
                self.mode, self.msg = "list", ""
            self.refresh()
            return
        if self.mode == "list" and name in ("LEFT", "RIGHT", "BAR_LEFT", "BAR_RIGHT"):
            self.across()
            self.refresh()
            return
        super().key(name)

    def across(self):
        """← / →: the other column, on the same row (or the right column's last)."""
        n = len(ITEMS)
        if self.choice < n:
            self.choice = n + min(self.choice, len(MAIN) - 1)
        else:
            self.choice -= n
        self.msg = ""

    def turn(self, delta):
        if self.mode in ("clear", "clear_all", "paste"):
            return
        if self.mode in ("load", "machine"):
            n = len(self.kits if self.mode == "load" else self.machines)
            if n:
                self.pick = max(0, min(n - 1, self.pick + delta))
            self.msg = ""
            return
        if self.mode == "list":
            self.choice = (self.choice + delta) % ALL          # down the left, on to the right, round again
            self.msg = ""
            return
        self.replace = None
        super().turn(delta)

    def name_key(self, name):
        if name not in menu.CONFIRM:
            self.replace = None
        super().name_key(name)

    def char(self, ch):
        if ch not in ("\r", "\n"):
            self.replace = None
        super().char(ch)

    # ------------------------------------------------------------ actions

    def choose(self):
        if self.choice >= len(ITEMS):
            self.open_main(MAIN[self.choice - len(ITEMS)][0])
            return
        if not self.drums:
            self.say("THE DRUM SYNTH ISN'T RUNNING")
            return
        what = ITEMS[self.choice][0]
        if what == "MACHINE":
            import drums
            self.machines = drums.available_machines()
            ids = [m for m, _ in self.machines]
            self.pick = ids.index(self.drums.machine) if self.drums.machine in ids else 0
            self.mode, self.msg = "machine", ""
            return
        if what == "SAVE":
            self.mode = "name"
            taken = {n.lower() for n in kit_names(self.drums.machine)}
            n = 1
            while ("preset %d" % n) in taken:
                n += 1
            self.name = list("Preset %d" % n)
            self.cursor = len(self.name)
            self.msg, self.replace = "", None
        elif what == "COPY":
            if self.seq.pattern.empty():
                self.say("PATTERN %d IS EMPTY: NOTHING TO COPY" % (self.seq.current + 1))
                return
            self.pattern_clip = (self.drums.machine, self.seq.current, copy.deepcopy(self.seq.pattern))
            self.close()
            self.transport.say("PATTERN %d COPIED: GO TO ANOTHER WITH KNOB 10, THEN FILE > PASTE" %
                               (self.seq.current + 1), 4)
        elif what == "PASTE":
            if not self.pattern_clip:
                self.say("NOTHING COPIED YET: COPY A PATTERN FIRST")
                return
            if self.pattern_clip[0] != self.drums.machine:
                self.say("THAT PATTERN IS FROM ANOTHER DRUM MACHINE")
                return
            if self.seq.pattern.empty():
                self.paste_pattern()
                return
            self.mode, self.msg = "paste", ""
        elif what == "CLEAR_ALL":
            if self.seq.pattern.empty():
                self.say("PATTERN %d IS ALREADY EMPTY" % (self.seq.current + 1))
                return
            self.mode, self.msg = "clear_all", ""
        elif what == "CLEAR":
            if not self.lock_count()[1]:
                self.say("THIS PATTERN HAS NO LOCKS OR CHANGED STEPS")
                return
            self.mode, self.msg = "clear", ""
        else:
            self.kits = kit_names(self.drums.machine)
            if not self.kits:
                self.say("NO SAVED PRESETS YET: SAVE ONE FIRST")
                return
            self.mode, self.msg = "load", ""
            self.pick = min(self.pick, len(self.kits) - 1)

    def open_main(self, what):
        """The right column: the project menu, doing what was chosen there."""
        m = self.main
        if not m:
            return
        self.close()
        m.open, m.mode, m.msg, m.confirm_new = True, "list", "", False
        m.choice = [w for w, _ in menu.ITEMS].index(what)
        m.choose()
        m.refresh()

    def create(self):
        """PLAY while naming: save the kit under that name."""
        name = "".join(self.name).strip()
        if not name:
            self.say("GIVE IT A NAME FIRST")
            return
        if name.startswith("."):
            self.say("A NAME CAN'T START WITH A DOT")
            return
        same = [n for n in kit_names(self.drums.machine) if n.lower() == name.lower()]
        if same and self.replace != name:
            self.replace = name
            self.say("THERE'S ALREADY A PRESET CALLED %s: PLAY AGAIN TO REPLACE IT" % name.upper())
            return
        try:
            os.makedirs(kits_dir(self.drums.machine), exist_ok=True)
            for old in same:
                if old != name:
                    os.remove(kit_path(old, self.drums.machine))        # "kit 1" replacing "Kit 1": one file, the new spelling
            tmp = kit_path(name, self.drums.machine) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._preset_data(name), f)
            os.replace(tmp, kit_path(name, self.drums.machine))
        except OSError as err:
            self.say("COULDN'T SAVE: %s" % str(err).upper())
            return
        self.replace = None
        self.close()
        self.transport.say("PRESET SAVED: %s" % name.upper(), 3)

    def _preset_data(self, name):
        """What a preset keeps: the instrument's settings; the sampler's samples by file too (so adding samples
        later doesn't move them); and the instrument's INSERT 1 and 2 with their settings."""
        d = self.drums
        data = {"name": name, "machine": d.machine, "values": d.kit()}
        if d.machine == "sampler":
            import sampler
            files, values = list(getattr(d, "files", [])), data["values"]
            data["samples"] = {}                     # "3": drum 4's first sample, "b3": its second, "c3"-"e3": 3-5
            for v in range(sampler.LANES):
                for w, tag in enumerate(("", "b", "c", "d", "e")):
                    k = sampler.sample_param(v, w)
                    if k < len(values) and 0 < values[k] <= len(files):
                        data["samples"][tag + str(v)] = files[values[k] - 1]
        slot = getattr(self.engine, "slot", None)
        T = self.transport
        if slot is not None and hasattr(T, "insfx") and getattr(self.engine, "core", None) is not None:
            try:
                data["inserts"] = [T.insfx(slot, p).to_json() for p in (0, 1)]
            except Exception:                        # noqa: BLE001
                pass
        return data

    def load(self):
        if not self.kits:
            return
        name = self.kits[self.pick]
        try:
            with open(kit_path(name, self.drums.machine)) as f:
                data = json.load(f)
            values = list(data["values"])
        except (OSError, ValueError, KeyError, TypeError) as err:
            self.say("COULDN'T LOAD %s: %s" % (name.upper(), str(err).upper()[:40]))
            return
        e = self.engine
        missing = 0
        samples = data.get("samples") if isinstance(data, dict) else None
        if samples and self.drums.machine == "sampler":      # find each sample by its file, wherever it is in the list now
            import sampler
            files = list(getattr(self.drums, "files", []))
            by_name = {}
            for i, f in enumerate(files):
                by_name.setdefault(os.path.basename(f).lower(), i)
            for v, path in samples.items():
                v = str(v)
                w = "bcde".index(v[0]) + 1 if v[:1] in ("b", "c", "d", "e") else 0
                k = sampler.sample_param(int(v[1:] if w else v), w)
                if not 0 <= k < len(values):
                    continue
                if path in files:
                    values[k] = files.index(path) + 1
                elif os.path.basename(path).lower() in by_name:      # moved to another folder: the same file name
                    values[k] = by_name[os.path.basename(path).lower()] + 1
                else:
                    values[k] = 0
                    missing += 1
        self.drums.load_kit(values)
        inserts = data.get("inserts") if isinstance(data, dict) else None
        slot = getattr(e, "slot", None)
        T = self.transport
        if isinstance(inserts, list) and slot is not None and hasattr(T, "insfx") and getattr(e, "core", None) is not None:
            try:                                     # (a preset saved before presets kept inserts: these stay as they are)
                for p in (0, 1):
                    saved = inserts[p] if p < len(inserts) else None
                    ins = T.insfx(slot, p)
                    if saved and saved.get("fx"):
                        ins.from_json(saved)
                    elif ins.index:
                        ins.choose(0)
                T._insfx_save()
            except Exception as err:                 # noqa: BLE001
                print("preset inserts:", err)
        with e.lock:
            e.dirty.add(-1)                         # the song keeps the kit it's using
        self.close()
        self.transport.say("PRESET LOADED: %s%s" % (name.upper(), "  (%d SAMPLE%s MISSING)" % (
            missing, "" if missing == 1 else "S") if missing else ""), 3)

    def item_y(self, item):
        """Where a menu item sits: the drums menu's 7 rows, evenly spaced."""
        names = [n for _, n in ITEMS]
        if item in names:
            return ITEM_TOP + ITEM_GAP * names.index(item)
        right = [n for _, n in MAIN]
        return ITEM_TOP + ITEM_GAP * right.index(item) if item in right else 0

    def switch_machine(self):
        """This song's drum machine. Each one keeps its own kit and its own patterns in the song."""
        if not self.machines:
            return
        mid, title = self.machines[self.pick]
        e, t = self.engine, self.transport
        if mid == self.drums.machine:
            self.say("THIS SLOT IS ALREADY THE %s" % title)
            return
        if e.slot_of(mid) is not None:
            self.say("THE %s IS IN SLOT %d ALREADY (EACH MACHINE CAN BE IN ONE SLOT)" % (title, e.slot_of(mid) + 1))
            return
        if not e.set_drum_machine(mid):
            self.say("THE %s ISN'T BUILT YET: RUN ~/console/pi-app/setup.sh ONCE" % title)
            return
        t.reset_drum_view()
        self.close()
        t.say("SLOT %d: %s  (ITS OWN PRESETS AND PATTERNS)" % (e.slot + 1, title), 4)

    def paste_pattern(self):
        """The copied pattern onto the current one (SHIFT+CUT on the sequencer undoes it)."""
        _, src, pat = self.pattern_clip
        dst = self.seq.current
        self.seq.snapshot()
        with self.seq.lock:
            self.seq.patterns[dst] = copy.deepcopy(pat)
        self.engine.seq_changed()
        self.close()
        self.transport.say("PATTERN %d PASTED ONTO PATTERN %d" % (src + 1, dst + 1), 3)

    def clear_pattern(self):
        """The current pattern back to empty, like a new one (SHIFT+CUT on the sequencer undoes it)."""
        self.seq.snapshot()
        with self.seq.lock:
            if isinstance(self.seq, notes.NoteSequencer):
                self.seq.patterns[self.seq.current] = notes.NotePattern(self.seq.new_length())
            else:
                self.seq.patterns[self.seq.current] = sequencer.Pattern(self.seq.new_length())
        self.engine.seq_changed()
        self.close()
        self.transport.say("PATTERN %d CLEARED" % (self.seq.current + 1), 3)

    def on_count(self):
        """Steps on in the current pattern (a synth's: notes)."""
        if isinstance(self.seq, notes.NoteSequencer):
            return sum(len(step) for step in self.seq.pattern.notes.values())
        return sum(st.on for ln in self.seq.pattern.lanes for st in ln.steps)

    def lock_count(self):
        """(locks, steps with locks or changed velocity / chance / ratchets) in the current pattern (a synth's:
        notes with locks or changed velocity / chance / ratchets)."""
        if isinstance(self.seq, notes.NoteSequencer):
            ns = [n for step in self.seq.pattern.notes.values() for n in step.values()
                  if n.locks or n.vel != sequencer.DEFAULT_VELOCITY or n.chance or n.ratchet != 1]
            return sum(len(n.locks) for n in ns), len(ns)
        steps = [s for ln in self.seq.pattern.lanes for s in ln.steps
                 if s.locks or s.vel != sequencer.DEFAULT_VELOCITY or s.chance or s.ratchet != 1]
        return sum(len(s.locks) for s in steps), len(steps)

    def clear_locks(self):
        self.seq.snapshot()                           # key 8 on the sequencer undoes it
        with self.seq.lock:
            if isinstance(self.seq, notes.NoteSequencer):
                for step in self.seq.pattern.notes.values():
                    for n in step.values():
                        n.locks.clear()
                        n.vel, n.chance, n.ratchet = sequencer.DEFAULT_VELOCITY, 0, 1
            for ln in getattr(self.seq.pattern, "lanes", []):
                for st in ln.steps:
                    st.locks.clear()
                    st.vel, st.chance, st.ratchet = sequencer.DEFAULT_VELOCITY, 0, 1     # step settings too
        self.engine.seq_changed()
        self.close()
        self.transport.say("LOCKS AND STEP SETTINGS CLEARED IN PATTERN %d" % (self.seq.current + 1), 3)

    # ------------------------------------------------------------ drawing

    def refresh(self):
        s = self.s
        s.set("song", t="DRUMS")
        self.choice = min(self.choice, ALL - 1)
        listing, loading = self.mode == "list", self.mode in ("load", "machine")
        texts = TEXTS
        for label, item in menu.ITEMS:
            s.set(item, t="")
        for i, (label, item) in enumerate(ITEMS):
            on = i == self.choice
            s.set(item, t=texts[label] if listing else "", c=menu.ON if on else menu.OFF, x=LEFT_X,
                  s=menu.SIZE_ON if on else menu.SIZE_OFF, y=self.item_y(item) - (2 if on else 0))
        for i, (label, item) in enumerate(MAIN):
            on = len(ITEMS) + i == self.choice
            s.set(item, t=MAIN_TEXTS[label] if listing else "", c=menu.ON if on else menu.OFF, x=RIGHT_X,
                  s=menu.SIZE_ON if on else menu.SIZE_OFF, y=self.item_y(item) - (2 if on else 0))
        # the LOAD list, in the settings rows
        names = getattr(self, "kits", []) if self.mode == "load" else [
            title + ("   (THIS SLOT)" if self.drums and mid == self.drums.machine else
                     "   (SLOT %d)" % (self.engine.slot_of(mid) + 1) if self.engine.slot_of(mid) is not None else "")
            for mid, title in getattr(self, "machines", [])]
        top = max(0, min(self.pick - ROWS // 2, len(names) - ROWS)) if loading else 0
        for r in range(ROWS):
            i = top + r
            name = names[i] if loading and i < len(names) else ""
            on = loading and i == self.pick
            s.set("set_label%d" % (r + 1), t="")
            s.set("set_value%d" % (r + 1), t=name, c=menu.ON if on else "#F2F3F5", x=640, a="center")
        bar = s.get("menu_bar")
        if bar:
            if loading:
                s.set("menu_bar", x=-180, y=self.bar_y("set_value%d" % (self.pick - top + 1)), h=bar["h"], w=1280 + 180)
            elif self.choice < len(ITEMS):
                item = ITEMS[self.choice][1]
                s.set("menu_bar", x=-180, y=self.bar_y(item), h=bar["h"] if listing else 0, w=LEFT_X + 30 + 180)
            else:
                item = MAIN[self.choice - len(ITEMS)][1]
                s.set("menu_bar", x=RIGHT_X - 30, y=self.bar_y(item), h=bar["h"] if listing else 0,
                      w=1280 - RIGHT_X + 30 + 180)
        if listing:
            s.set("prompt", t="")
            s.set("name_text", t="")
            hint = "BIG KNOB: MOVE     LEFT / RIGHT: OTHER COLUMN     PLAY: CHOOSE     FILE: BACK TO THE DRUMS"
        elif loading:
            s.set("prompt", t="")
            s.set("name_text", t="")
            hint = ("LOAD A PRESET     BIG KNOB: PICK ONE     PLAY: LOAD IT     FILE: BACK" if self.mode == "load" else
                    "DRUM MACHINE FOR THIS SLOT     BIG KNOB: PICK ONE     PLAY: SWITCH     FILE: BACK")
        elif self.mode == "paste":
            s.set("prompt", t="PASTE PATTERN %d ONTO" % (self.pattern_clip[1] + 1), y=self.prompt_y)
            s.set("name_text", t="PATTERN %d?" % (self.seq.current + 1))
            hint = "IT HAS STEPS: PASTING REPLACES THEM     PLAY: PASTE     FILE: BACK"
        elif self.mode == "clear_all":
            on = self.on_count()
            s.set("prompt", t="CLEAR PATTERN %d?" % (self.seq.current + 1), y=self.prompt_y)
            s.set("name_text", t="%d %s ON" % (on, ("NOTE" if on == 1 else "NOTES") if isinstance(self.seq, notes.NoteSequencer) else ("STEP" if on == 1 else "STEPS")))
            hint = "PLAY: CLEAR (STEPS, LOCKS, LENGTHS AND RATES, LIKE A NEW PATTERN)     FILE: BACK"
        elif self.mode == "clear":
            locks, steps = self.lock_count()
            s.set("prompt", t="CLEAR THE LOCKS AND STEP SETTINGS IN PATTERN %d?" % (self.seq.current + 1), y=self.prompt_y)
            s.set("name_text", t="%d LOCK%s ON %d STEP%s" % (locks, "" if locks == 1 else "S", steps, "" if steps == 1 else "S"))
            hint = "PLAY: CLEAR (VELOCITY 100, CHANCE 100%, NO RATCHETS; STEPS STAY ON OR OFF)   FILE: BACK"
        else:
            s.set("prompt", t="NAME THIS PRESET", y=self.prompt_y)
            s.set("name_text", t="".join(self.name) or " ")
            hint = "BIG KNOB: LETTER   ARROW KEYS: MOVE   CUT: DELETE   PLAY: SAVE   FILE: CANCEL"
        s.set("menu_hint", t=hint)
        s.set("menu_msg", t=self.msg)

    def draw(self, surf):
        self.s.draw(surf)
