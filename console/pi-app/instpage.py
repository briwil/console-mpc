"""The INSTRUMENTS page (the MIDI key from the tape page): 8 slots, each empty, a drum machine or a synth. It's where you choose what's loaded; the patterns are made on the drum and sequencer
pages, and recorded onto the tape like anything else.

- Knob 11 (the big knob) picks a slot.
- Push knob 11: on an empty slot, pick an instrument for it; on a loaded one, open it (its drum page; the
  MIDI key then goes between the drum page and its sequencer, SHIFT+MIDI comes back here).
- SHIFT + push knob 11 on a loaded slot: CHANGE INSTRUMENT or REMOVE. A removed machine's kit and patterns
  stay in the song, so putting it back finds them.
- Track keys 1-8 mute and unmute slots 1-8.
- SHIFT+MIDI: back to the tape page.

Each machine can be in one slot. Here every loaded slot that isn't muted plays (and the tape doesn't);
on the tape page only the slots an armed track records from play.
"""
import time

import pygame

import audio
import ui

MENU = ["CHANGE INSTRUMENT", "REMOVE"]
EDIT = "__edit__"          # the last entry of the picker: choose which instruments it lists
BUILDING = "MORE ARE BEING BUILT (THE FIRST TIME TAKES A FEW MINUTES)..."


def building():
    import drums
    return bool(drums.schwung_modules and drums.schwung_modules.building)


def is_synth(mid):
    import drums
    sm = drums.schwung_modules
    return bool(sm and mid in sm.catalog.BY_ID and sm.catalog.BY_ID[mid]["kind"] == "synth")


def machines():
    import drums
    return drums.available_machines()


class InstPage:
    def __init__(self, transport):
        self.t = transport
        self.row = 0                 # the slot picked, 0-7
        self.mode = None             # None, "pick" (an instrument for the slot), "menu" (change / remove) or "edit" (show / hide)
        self.items = []              # "edit": [(machine id or None for a heading, title)]
        self.pick = 0
        self.choices = []            # "pick": [(machine id, title)]; "menu": MENU

    @property
    def e(self):
        return self.t.engine

    def title(self, mid):
        return dict(machines()).get(mid, (mid or "").upper())

    # ------------------------------------------------------------ controls

    def knob(self, number, delta):
        if number != 11:
            return
        step = 1 if delta > 0 else -1
        if self.mode == "edit":
            n = len(self.items)
            for _ in range(n):                                # (the headings are skipped)
                self.pick = (self.pick + step) % n
                if self.items[self.pick][0] is not None:
                    break
        elif self.mode:
            self.pick = (self.pick + step) % max(1, len(self.choices))
        else:
            self.row = max(0, min(audio.SLOTS - 1, self.row + step))

    def push(self):
        """Push knob 11 (or the MIDI key): choose in the list, open a loaded slot, or pick for an empty one."""
        e = self.e
        if not e or not e.drums:
            return
        if self.mode == "pick":
            self.choose_machine()
        elif self.mode == "edit":
            self.toggle()
        elif self.mode == "menu":
            if self.choices[self.pick] == "REMOVE":
                self.remove()
            else:
                self.start_pick()
        elif e.slots[self.row]:
            self.open()
        else:
            self.start_pick()

    def wheel_push(self):
        """SHIFT + push the wheel (the Move): on a loaded slot, change or remove it; otherwise as push."""
        e = self.e
        if not self.mode and e and e.drums and e.slots[self.row]:
            self.shift_push()
        else:
            self.push()

    def shift_push(self):
        """SHIFT + push knob 11 on a loaded slot: change or remove it."""
        e = self.e
        if self.mode or not e or not e.slots[self.row]:
            return
        self.mode, self.choices, self.pick = "menu", list(MENU), 0

    def cancel(self):
        if self.mode == "edit":
            self.start_pick()                                  # Back from the list: the picker again
            return
        self.mode = None

    # ------------------------------------------------------------ which instruments the picker lists
    def hidden(self):
        e = self.e
        return set(e.settings.get("hidden_instruments", [])) if e else set()

    def start_edit(self):
        """EDIT: every drum machine, then every synth, each with a check box. Unchecked ones leave the picker
        (a song that already uses one still has it)."""
        found = machines()
        drums = sorted(((m, t) for m, t in found if not is_synth(m)), key=lambda c: c[1].lower())
        synths = sorted(((m, t) for m, t in found if is_synth(m)), key=lambda c: c[1].lower())
        self.items = [(None, "DRUM MACHINES")] + drums + [(None, "SYNTHS")] + synths
        self.pick = 1 if drums else (len(drums) + 2 if synths else 0)
        self.mode = "edit"
        self.labels()

    def labels(self):
        hid = self.hidden()
        self.choices = [("-- %s --" % t) if m is None else ("%s %s" % ("( )" if m in hid else "(X)", t.upper()))
                        for m, t in self.items]

    def toggle(self):
        mid, title = self.items[self.pick]
        if mid is None:
            return
        hid = self.hidden()
        hid = hid - {mid} if mid in hid else hid | {mid}
        self.e.remember("hidden_instruments", sorted(hid))
        self.labels()
        self.t.say("%s: %s" % (title.upper(), "HIDDEN FROM THE LIST" if mid in hid else "SHOWN IN THE LIST"), 2)

    def start_pick(self):
        e = self.e
        mine = e.slots[self.row]
        hid = self.hidden()
        self.choices = sorted(((m, title) for m, title in machines()
                               if (e.slot_of(m) is None or m == mine) and (m not in hid or m == mine)),
                              key=lambda c: (is_synth(c[0]), c[1].lower()))   # (drum machines A to Z, then synths A to Z)
        if not machines():
            self.mode = None
            self.t.say("NO DRUM MACHINES ARE BUILT: RUN ~/console/pi-app/setup.sh ONCE", 4)
            return
        self.choices.append((EDIT, "EDIT"))                     # (always last)
        ids = [m for m, _ in self.choices]
        self.pick = ids.index(mine) if mine in ids else 0
        self.mode = "pick"

    def choose_machine(self):
        e = self.e
        mid, title = self.choices[self.pick]
        if mid == EDIT:
            self.start_edit()
            return
        self.mode = None
        if mid == e.slots[self.row]:
            self.open()                                  # (the one it had: straight to it)
            return
        if not e.set_slot(self.row, mid):
            self.t.say("THE %s ISN'T BUILT YET: RUN ~/console/pi-app/setup.sh ONCE" % title, 4)
            return
        if e.slot == self.row:
            self.t.reset_drum_view()
        self.open()                                      # chosen: straight to its page
        self.t.say("SLOT %d: %s" % (self.row + 1, title), 3)

    def remove(self):
        e = self.e
        self.mode = None
        title = self.title(e.slots[self.row])
        shown = e.slot == self.row
        e.set_slot(self.row, None)
        if shown:
            self.t.reset_drum_view()
        self.t.say("SLOT %d EMPTY  (THE %s'S KIT AND PATTERNS STAY IN THE SONG IF YOU PUT IT BACK)" %
                   (self.row + 1, title), 4)

    def open(self):
        """The slot's drum page."""
        e, t = self.e, self.t
        if e.slot != self.row:
            e.open_slot(self.row)
            t.reset_drum_view()
        t.inst_page = False
        t.drum_page, t.seq_page = True, False
        problem = getattr(e.drums.m, "problem", lambda: "")()
        if problem:
            t.say(problem.upper()[:110], 6)        # e.g. JE-8086 without its ROM

    def mute(self, n):
        """Track key n: mute or unmute slot n."""
        e = self.e
        if not e or not 1 <= n <= audio.SLOTS:
            return
        if not e.slots[n - 1]:
            self.t.say("SLOT %d IS EMPTY" % n, 2)
            return
        on = e.mute_slot(n - 1)
        self.t.say("SLOT %d (%s) %s" % (n, self.title(e.slots[n - 1]), "MUTED" if on else "ON"), 2)

    def solo(self, n):
        """Shift + track key n: solo slot n (again: everyone back)."""
        e = self.e
        if not e or not 1 <= n <= audio.SLOTS:
            return
        if not e.slots[n - 1]:
            self.t.say("SLOT %d IS EMPTY" % n, 2)
            return
        on = e.solo_slot(n - 1)
        self.t.say("SLOT %d (%s) %s" % (n, self.title(e.slots[n - 1]), "SOLO" if on else "SOLO OFF"), 2)

    def hint(self):
        e = self.e
        if self.mode == "pick":
            return "INSTRUMENT FOR SLOT %d  ·  KNOB 11: PICK  ·  PUSH KNOB 11: CHOOSE  ·  SHIFT+MIDI: CANCEL" % (self.row + 1)
        if self.mode == "edit":
            return "SHOW OR HIDE INSTRUMENTS  ·  PUSH KNOB 11: TICK / UNTICK  ·  SHIFT+MIDI: BACK"
        if self.mode == "menu":
            return "SLOT %d  ·  KNOB 11: PICK  ·  PUSH KNOB 11: CHOOSE  ·  SHIFT+MIDI: CANCEL" % (self.row + 1)
        if e and e.slots[self.row]:
            return "PUSH KNOB 11: OPEN  ·  SHIFT+PUSH: CHANGE OR REMOVE  ·  TRACK KEYS: MUTE  ·  SHIFT+MIDI: TAPE"
        return "KNOB 11: PICK A SLOT  ·  PUSH KNOB 11: ADD AN INSTRUMENT  ·  TRACK KEYS: MUTE  ·  SHIFT+MIDI: TAPE"

    # ------------------------------------------------------------ drawing

    def draw(self, surf):
        s, e, t = self.t.s, self.e, self.t
        bg, panel, lane_col = (12, 13, 16), (20, 22, 26), (23, 25, 30)
        white, grey, dim, amber, green = (242, 243, 245), (125, 131, 140), (70, 75, 84), (255, 181, 71), (60, 203, 127)
        f = lambda size, weight=600, fam="mono": s.font(fam, weight, size)
        surf.set_clip(None)
        surf.fill(bg)
        pygame.draw.rect(surf, panel, (0, 0, 1280, 36))
        surf.blit(f(18).render("CONSOLE", True, white), (20, 8))
        surf.blit(f(15, 500, "sans").render("INSTRUMENTS", True, grey), (120, 10))
        if e:
            bpm = f(15).render("%.1f BPM  %s" % (e.bpm, e.time_sig if isinstance(e.time_sig, str) else
                                                  "%d/%d" % tuple(e.time_sig)), True, white)
            surf.blit(bpm, (1260 - bpm.get_width(), 10))
        sounding = set(e.sounding_slots()) if e else set()
        for i in range(audio.SLOTS):
            tab = s.get("track%d_tab" % (i + 1)) or {"x": 20, "y": 50 + 39 * i, "w": 32, "h": 33, "c": "#4F8CFF"}
            lane = s.get("track%d_lane" % (i + 1)) or {"x": 60, "y": tab["y"], "w": 1140, "h": 33}
            mid = e.slots[i] if e else None
            muted = e and i in e.slot_mutes
            colour = ui.rgb(tab["c"]) if isinstance(tab["c"], str) else tuple(tab["c"])
            pygame.draw.rect(surf, colour if mid and not muted else (40, 43, 50),
                             (tab["x"], tab["y"], tab["w"], tab["h"]), border_radius=6)
            num = f(16).render(str(i + 1), True, bg)
            surf.blit(num, (tab["x"] + (tab["w"] - num.get_width()) // 2, tab["y"] + (tab["h"] - num.get_height()) // 2))
            lx, ly, lw, lh = lane["x"], lane["y"], 1200 - lane["x"], lane["h"]
            pygame.draw.rect(surf, lane_col, (lx, ly, lw, lh), border_radius=4)
            mid_y = ly + lh // 2
            if not mid:
                txt = f(14, 500).render("EMPTY", True, dim)
                surf.blit(txt, (lx + 14, mid_y - txt.get_height() // 2))
            else:
                name = f(18, 700).render(self.title(mid), True, dim if muted else white)
                surf.blit(name, (lx + 14, mid_y - name.get_height() // 2))
                seq = e.seqs.get(mid)
                if seq is not None:
                    self.draw_pattern(surf, seq, (lx + 250, ly + 7, 640, lh - 14), dim if muted else colour)
                    pat = f(13).render("PATTERN %d" % (seq.current + 1), True, grey)
                    surf.blit(pat, (lx + 910, mid_y - pat.get_height() // 2))
                tag, tag_col = ("MUTED", amber) if muted else ("PLAYING", green) if (i in sounding and e.playing) else ("", grey)
                if e.slot == i:
                    tag = (tag + "  ·  " if tag else "") + "EDITING"
                if tag:
                    tg = f(13).render(tag, True, tag_col)
                    surf.blit(tg, (lx + lw - 14 - tg.get_width(), mid_y - tg.get_height() // 2))
            if i == self.row:
                pygame.draw.rect(surf, white, (lx - 2, ly - 2, lw + 4, lh + 4), 2, border_radius=6)
        # the bottom line: a message, else what the controls do
        pygame.draw.rect(surf, panel, (0, 368, 1280, 32))
        busy = t.message and time.monotonic() < t.message_until and not self.mode
        hint = t.message if busy else self.hint()
        h = f(13).render(hint, True, grey)
        surf.blit(h, (640 - h.get_width() // 2, 376))
        if self.mode:
            self.draw_list(surf, f, white, grey, dim, green)

    def draw_pattern(self, surf, seq, rect, colour):
        """The current pattern at a glance: a tick for each step that has a hit on any lane (a synth: a
        note starting there)."""
        x, y, w, h = rect
        pat = seq.pattern
        synth = hasattr(pat, "notes")
        length = pat.length if synth else max([ln.length for ln in pat.lanes] + [1])
        length = min(length, 64)
        cell = w / length
        for k in range(length):
            on = bool(pat.at(k)) if synth else any(k < ln.length and ln.steps[k].on for ln in pat.lanes)
            cx = round(x + k * cell)
            cw = max(2, round(cell) - 2)
            if on:
                pygame.draw.rect(surf, colour, (cx, y, cw, h), border_radius=2)
            else:
                pygame.draw.rect(surf, (40, 43, 50), (cx, y + h // 2 - 1, cw, 2))

    def draw_list(self, surf, f, white, grey, dim, green):
        """The pick list (or the CHANGE / REMOVE menu): 6 rows at a time, scrolling with the pick."""
        if self.mode == "pick":
            items = [(title, "" if mid == EDIT else "SYNTH" if is_synth(mid) else "DRUMS") for mid, title in self.choices]
        else:
            items = [(label, "") for label in self.choices]
        rows = 6
        w, row_h = 560, 38
        shown = min(rows, len(items))
        extra = 1 if (self.mode == "pick" and building()) else 0
        h = 56 + row_h * (shown + extra)
        x, y = 640 - w // 2, max(40, 200 - h // 2)
        pygame.draw.rect(surf, (20, 22, 26), (x, y, w, h), border_radius=10)
        pygame.draw.rect(surf, (70, 75, 84), (x, y, w, h), 2, border_radius=10)
        head = "INSTRUMENT FOR SLOT %d" % (self.row + 1) if self.mode == "pick" else \
            "SHOW OR HIDE" if self.mode == "edit" else "SLOT %d" % (self.row + 1)
        if len(items) > rows:
            head += "   (%d OF %d)" % (self.pick + 1, len(items))
        hd = f(13).render(head, True, grey)
        surf.blit(hd, (640 - hd.get_width() // 2, y + 14))
        top = max(0, min(self.pick - rows // 2, len(items) - rows))
        for r in range(shown):
            k = top + r
            label, kind = items[k]
            ry = y + 42 + r * row_h
            on = k == self.pick
            if on:
                pygame.draw.rect(surf, (35, 38, 45), (x + 12, ry, w - 24, row_h - 4), border_radius=6)
            txt = f(22 if on else 20, 600, "sans").render(label, True, green if on else white)
            surf.blit(txt, (640 - txt.get_width() // 2, ry + (row_h - 4 - txt.get_height()) // 2))
            if kind:
                tg = f(11).render(kind, True, dim if not on else grey)
                surf.blit(tg, (x + w - 24 - tg.get_width(), ry + (row_h - 4 - tg.get_height()) // 2))
        if top > 0:
            pygame.draw.polygon(surf, grey, [(640 - 8, y + 38), (640 + 8, y + 38), (640, y + 31)])
        if top + rows < len(items):
            by = y + 42 + shown * row_h - 2
            pygame.draw.polygon(surf, grey, [(640 - 8, by), (640 + 8, by), (640, by + 7)])
        if extra:
            ry = y + 42 + shown * row_h
            txt = f(12).render(BUILDING, True, dim)
            surf.blit(txt, (640 - txt.get_width() // 2, ry + 8))
