"""Choosing an insert effect: one picture at a time, like choosing an instrument (the wheel turns, push chooses,
Back leaves). The pictures are in move/fximg/<id>.txt."""


class FxPicker:
    img_dir = "fximg"

    def __init__(self, T):
        self.T = T
        self.active = False
        self.choices = []                  # [(id, title)]
        self.pick = 0
        self.ins = None
        self.editing = False               # EDIT: the show / hide list (choices are then its labels)
        self.items = []                    # EDIT: [(effect id, title)]

    def hidden(self):
        e = self.T.engine
        return set(e.settings.get("hidden_effects", [])) if e else set()

    def open(self, ins):
        import catalog
        import insertfx
        self.ins = ins
        song = getattr(ins, "slot", 0) == -1                 # a song insert: not the effects too heavy for it
        skip = insertfx.SONG_SKIP if song else ()
        # (id, title, its number in the catalog): the list can leave some out, so the number is kept with each
        hid = self.hidden()
        self.choices = [("none", "NO EFFECT", 0)] + sorted(     # (NO EFFECT first, then A to Z)
            ((f["id"], f["title"].upper(), i) for i, f in enumerate(catalog.FX, 1)
             if f["id"] not in skip and (f["id"] not in hid or i == ins.index)),     # (the one in use stays)
            key=lambda c: c[1])
        self.choices.append(("__edit__", "EDIT", -1))              # (always last)
        self.pick = next((k for k, c in enumerate(self.choices) if c[2] == ins.index), 0)
        self.editing = False
        self.active = True

    def start_edit(self):
        """EDIT: every effect with a tick box; an unticked one leaves the list."""
        import catalog
        self.items = sorted(((f["id"], f["title"].upper()) for f in catalog.FX), key=lambda c: c[1])
        self.editing = True
        self.pick = 0
        self.labels()

    def labels(self):
        hid = self.hidden()
        self.choices = [("%s %s" % ("( )" if i in hid else "(X)", t), t) for i, t in self.items]

    def toggle(self):
        i, title = self.items[self.pick]
        hid = self.hidden()
        hid = hid - {i} if i in hid else hid | {i}
        self.T.engine.remember("hidden_effects", sorted(hid))
        self.labels()
        self.T.say("%s: %s" % (title, "HIDDEN FROM THE LIST" if i in hid else "SHOWN IN THE LIST"), 2)

    def turn(self, delta):
        if self.choices:
            self.pick = (self.pick + (1 if delta > 0 else -1)) % len(self.choices)

    def push(self):
        ins = self.ins
        if self.editing:
            self.toggle()
            return
        if self.choices[self.pick][0] == "__edit__":
            self.start_edit()
            return
        ins.choose(self.choices[self.pick][2])
        self.active = False
        song = getattr(ins, "slot", 0) == -1                 # SONG INSERT 1 / 2: its copies start on every instrument
        if song:
            self.T.songfx_sync()
        self.T._insfx_save()
        self.T.say("%sINSERT %d: %s%s" % ("SONG " if song else "", ins.pos + 1, ins.name(),
                                          (" (" + ins.error + ")") if ins.error else ""), 2)

    def back(self):
        if self.editing:
            self.open(self.ins)                 # Back from the list: the picker again
            return
        self.active = False
