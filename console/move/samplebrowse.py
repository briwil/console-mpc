"""The SAMPLE BROWSER: choosing a sampler drum's sample by folders instead of one long list.

Push the big wheel on a sampler drum's page to open it (on a one-sample instrument like MRSAMPLE it goes straight to
the folders: one sample, played as a note). It first asks which of the drum's samples: SAMPLE 1 and
SAMPLE 2 (BLEND mixes them), then RANDOM (push: on / off). With RANDOM on, SAMPLES 3-5 come in above RANDOM, and each hit plays
one of them at random (BLEND off). Delete + push the wheel on a sample: take it out. Then: the wheel turns through the list, push the wheel to open a folder / choose
a sample, "< UP" goes up, Back goes up a folder (from the top: back to SAMPLE 1 / 2, and Back again leaves).
The highlighted sample is played as you land on it; leaving with Back puts the old sample back."""
import os
import threading


class SampleBrowser:
    def __init__(self, T):
        self.T = T
        self.active = False
        self._tree = None
        self._files = None
        self.root = "/"
        self.folder = "/"
        self.entries = []          # [(label, kind, value)]: kind "up" / "dir" (value: folder path) / "file" (value: index)
        self.pick = 0
        self.voice = 0
        self.which = 0             # the drum's first (0) or second (1) sample
        self.stage = "which"       # "which": SAMPLE 1 / SAMPLE 2; "files": the folders
        self.param = 0
        self.orig = 0
        self._timer = None
        self.single = False
        self._off = None
        self.last_file = None      # and the file it was on
        self.last_folder = None    # where the last pick left off: the next one starts there

    # ------------------------------------------------------------ the folders
    def _build(self, files):
        self._files = files
        tree = {}
        dirs = [os.path.dirname(p) for p in files]
        self.root = os.path.commonpath(dirs) if dirs else "/"
        for i, p in enumerate(files):
            d = os.path.dirname(p)
            tree.setdefault(d, {"dirs": set(), "files": []})["files"].append((os.path.basename(p), i + 1))
            while d != self.root and len(d) > len(self.root):
                parent = os.path.dirname(d)
                tree.setdefault(parent, {"dirs": set(), "files": []})["dirs"].add(d)
                d = parent
        self._tree = tree

    def _list(self):
        node = self._tree.get(self.folder, {"dirs": (), "files": []})
        rows = []
        if self.folder != self.root:
            rows.append(("< UP", "up", os.path.dirname(self.folder)))
        for d in sorted(node["dirs"], key=str.lower):
            rows.append(("> " + os.path.basename(d).upper(), "dir", d))
        for name, idx in sorted(node["files"], key=lambda x: x[0].lower()):
            rows.append((os.path.splitext(name)[0].upper(), "file", idx))
        self.entries = rows

    def title(self):
        if self.stage == "which":
            return "DRUM %d: WHICH SAMPLE?" % (self.voice + 1)
        rel = os.path.relpath(self.folder, self.root) if self.folder != self.root else os.path.basename(self.root)
        if self.single:
            return ("SAMPLE  %s" % rel.upper())[:27]
        return ("D%d S%d  %s" % (self.voice + 1, self.which + 1, rel.upper()))[:27]

    def _random(self):
        import sampler
        return bool(self.drums.get_param(sampler.RANDOM + self.voice)) if hasattr(sampler, "RANDOM") else False

    def _which_list(self):
        d = self.drums
        rnd = self._random()

        def row(w):
            name = d.sample_name(self.voice, w) if hasattr(d, "sample_name") else ""
            return ("SAMPLE %d  %s" % (w + 1, name if name != "EMPTY" else "-"), "which", w)
        self.entries = [row(0), row(1)]
        if rnd:
            self.entries += [row(w) for w in (2, 3, 4)]
        self.entries.append(("RANDOM  %s" % ("ON" if rnd else "OFF"), "random", None))      # (always last)

    # ------------------------------------------------------------ opening and leaving
    def open(self, drums, voice):
        files = drums.files
        if not files:
            self.T.say("NO SAMPLES FOUND", 3)
            return
        if self._files is not files or self._tree is None or len(files) != len(self._files or ()):
            self._build(files)
        self.drums, self.voice = drums, voice
        self.single = getattr(drums, "sample_param_index", None) is not None     # a one-sample instrument (MrSample)
        self.stage = "which"
        self._which_list() if not self.single else None
        self.pick = 0
        self.active = True
        if self.single:
            self._choose_which(0)                      # (no SAMPLE 1 / 2 / RANDOM: straight to the folders)

    def _choose_which(self, which):
        import sampler
        self.which, self.stage = which, "files"
        self.param = self.drums.sample_param_index if self.single else sampler.sample_param(self.voice, which)
        self.orig = self.drums.get_param(self.param)
        if hasattr(self.drums, "solo"):
            self.drums.solo(self.voice, which)            # while browsing, hear only the sample being chosen
        self.folder = self.last_folder if self.last_folder in (self._tree or {}) else self.root   # (where the last pick left off)
        self._list()
        self.pick = 0
        if self.folder == self.last_folder:                 # (and on the file it was on)
            self.pick = next((k for k, (_l, kind, v) in enumerate(self.entries) if kind == "file" and v == self.last_file), 0)

    def _remember(self):
        self.last_folder = self.folder
        if self.entries and self.pick < len(self.entries) and self.entries[self.pick][1] == "file":
            self.last_file = self.entries[self.pick][2]

    def _unsolo(self):
        if self._off:
            self._off.cancel()
            self._off = None
        if hasattr(self.drums, "solo"):
            self.drums.solo(self.voice, None)

    def remove(self):
        """Delete + push the wheel on a sample: take it out of the drum."""
        if self.stage != "which" or not self.entries:
            return
        _l, kind, w = self.entries[self.pick]
        if kind != "which":
            return
        import sampler
        self.drums.set_param(sampler.sample_param(self.voice, w), 0)
        self._which_list()
        self.T.say("DRUM %d: SAMPLE %d TAKEN OUT" % (self.voice + 1, w + 1), 2)

    def close(self, keep):
        if self.stage == "files":
            self._remember()
        self._cancel()
        if not keep and self.stage == "files":
            self.drums.set_param(self.param, self.orig)
        self._unsolo()
        self.active = False

    # ------------------------------------------------------------ controls
    def turn(self, delta):
        if not self.entries:
            return
        if self.stage == "which":                          # (SAMPLE 1 ... RANDOM: stops at both ends)
            self.pick = max(0, min(len(self.entries) - 1, self.pick + (1 if delta > 0 else -1)))
        else:
            self.pick = (self.pick + (1 if delta > 0 else -1)) % len(self.entries)
        self._preview()

    def push(self):
        if not self.entries:
            return
        _l, kind, val = self.entries[self.pick]
        if kind == "which":
            self._choose_which(val)
            return
        if kind == "random":
            import sampler
            on = not self._random()
            self.drums.set_param(sampler.RANDOM + self.voice, 1 if on else 0)
            self._which_list()
            self.pick = len(self.entries) - 1                  # (stay on the RANDOM row, now last)
            self.T.say("RANDOM %s" % ("ON: EACH HIT ONE OF THE SAMPLES, BLEND OFF" if on else "OFF: BLEND IS BACK"), 3)
            return
        if kind in ("up", "dir"):
            came = self.folder
            self.folder = val
            self._list()
            self.pick = 0
            if kind == "up":
                for k, (_l2, k2, v2) in enumerate(self.entries):
                    if v2 == came:
                        self.pick = k
        else:
            self._cancel()
            self.drums.set_param(self.param, val)
            self._unsolo()                             # (no sound as it goes back to the list)
            self._remember()
            if self.single:                            # a one-sample instrument: that was the choice, done
                self.active = False
                self.T.say("SAMPLE: %s" % self.drums.value_text(self.param), 2)
                return
            self.stage = "which"                       # (back to SAMPLE 1 / 2 ..., not out to the instrument)
            self._which_list()
            self.pick = next((k for k, (_l, kind, v) in enumerate(self.entries) if kind == "which" and v == self.which), 0)
            import sampler
            if self.which == 1 and not self._random() and self.drums.get_param(sampler.BLEND + self.voice) == 0:
                self.T.say("SAMPLE 2 IN. BLEND (KNOB 8) IS ALL ON SAMPLE 1: TURN IT TO HEAR IT", 4)

    def back(self):
        if self.stage == "which":
            self.close(False)
        elif self.folder != self.root:
            self.folder_up()
        elif self.single:                              # the top of the samples: leave (the old sample stays)
            self._remember()
            self.close(False)
        else:                                          # the top of the samples: back to SAMPLE 1 / 2
            self._remember()
            self._cancel()
            self.drums.set_param(self.param, self.orig)
            self._unsolo()
            self.stage = "which"
            self._which_list()
            self.pick = next((k for k, (_l, kind, v) in enumerate(self.entries) if kind == "which" and v == self.which), 0)

    def folder_up(self):
        came = self.folder
        self.folder = os.path.dirname(self.folder)
        self._list()
        self.pick = 0
        for k, (_l, kind, val) in enumerate(self.entries):
            if val == came:
                self.pick = k

    # ------------------------------------------------------------ hearing it
    def _cancel(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _hear(self, which):
        if self.active and self.stage == "which":
            self.drums.solo(self.voice, which)
            self.T.engine.hit(self.voice, 110)
            if self._off:
                self._off.cancel()
            self._off = threading.Timer(0.3, lambda: self.drums.solo(self.voice, None))   # (the hit has picked its sample by then)
            self._off.daemon = True
            self._off.start()

    def _preview(self):
        self._cancel()
        _l, kind, val = self.entries[self.pick]
        if self.stage == "which":                      # rolling over a sample in the list: hear just that one
            if kind == "which" and hasattr(self.drums, "solo"):
                import sampler
                if self.drums.get_param(sampler.sample_param(self.voice, val)):
                    self._timer = threading.Timer(0.25, self._hear, (val,))
                    self._timer.daemon = True
                    self._timer.start()
            return
        if kind != "file" or self.stage != "files":
            return

        def go():
            if self.active and self.stage == "files":
                self.drums.set_param(self.param, val)
                if self.single:
                    self.drums.hear()                  # (a note: it plays chromatically)
                else:
                    self.T.engine.hit(self.voice, 110)
        self._timer = threading.Timer(0.3, go)
        self._timer.daemon = True
        self._timer.start()
