"""The synth sequencer page (the MIDI key on a synth's sound page), to Brian's description: like the Deluge,
each row is a note of the scale (8 on screen, lowest at the bottom) and a step can hold a chord.

- Knob 1 moves the step cursor, 1 to 64 (the steps scroll under it, as on the drum sequencer).
- Track key n is the nth row from the bottom: pressing it picks that row and puts its note on the cursor's
  step (and plays it). Pressing it on a note that's there takes it off (when you let go, unless you turned
  a knob while holding it). While playing, a key puts the note where it's playing, as long as you hold it.
- Knobs 2-9 (NOTE mode) change the picked note: LENGTH (in steps; it holds over the next ones), VELOCITY,
  CHANCE, RATCHETS; then the pattern's LENGTH and RATE, and the song's KEY and SCALE for this synth.
- Push knob 1 for the next mode: the synth's sound pages. There, hold a note's key and turn to lock the
  setting to that note (a parameter lock); with no key held, the knobs change the synth's own sound.
- SHIFT + knob 6 (PATTERN LEN): the picked row's own length, so each row can loop on its own cycle (back at
  the pattern's length it follows the pattern again). Rows past their length are greyed out.
- Stopped, pressing a different row's key only picks that row (the note goes on as before); pressing it again
  takes a note off, like the drums.
- ← / →: the rows down / up an octave (SHIFT + ← / →: one row). Knob 10 picks the pattern.
"""
import time

import pygame

import notes
import sequencer
import ui

VISIBLE = 32
FOLLOW_AT = 15
NOTE_PARAMS = ["length", "vel", "chance", "ratchet", "pat_length", "rate", "root", "scale"]   # knobs 2-9
LABELS = {"length": "LENGTH", "vel": "VELOCITY", "chance": "CHANCE", "ratchet": "RATCHETS",
          "pat_length": "PATTERN LEN", "rate": "RATE", "root": "KEY", "scale": "SCALE"}
GESTURE_GAP = 1.5
HEAR_EVERY, HEAR_AFTER = 1.0, 0.5


class SynthPage:
    def __init__(self, transport):
        self.t = transport
        self.cursor = 0
        self.row = 0                 # the picked row on screen, 0 (bottom) - 7
        self.mode = 0                # 0: NOTE; 1...: the synth's sound pages
        self.held = {}               # row -> True once a knob turned while its key was held
        self.down = {}               # row -> (note, step it went on, when) for keys held while playing
        self.switching = {}          # row -> True when its key's press only picked the row (nothing is removed)
        self._gesture = None
        self._cursor_until = 0.0
        self._hear = None
        self._heard_at = self._turned_at = 0.0
        self._hear_due = False

    @property
    def e(self):
        return self.t.engine

    @property
    def seq(self):
        return self.t.engine.seq

    @property
    def d(self):
        return self.t.engine.drums

    def pages(self):
        return self.d.pages(0)

    def mode_name(self):
        return "NOTE" if self.mode == 0 else self.pages()[self.mode - 1][0]

    def params(self):
        return NOTE_PARAMS if self.mode == 0 else self.pages()[self.mode - 1][1]

    def picked(self):
        """(step, note) of the picked note: the one on the picked row that's sounding at the cursor."""
        pitch = self.seq.shown_notes()[self.row]
        step = self.seq.covering(self.cursor, pitch)
        return (step if step is not None else self.cursor), pitch

    def showing_cursor(self):
        return not self.e.playing or time.monotonic() < self._cursor_until

    def first_column(self):
        at = self.cursor
        if self.e.playing and not self.showing_cursor():
            at = self.seq.position(self.e._heard_frame(), self.e.frames_per_beat())[0]
        return max(0, min(sequencer.MAX_STEPS - VISIBLE, at - FOLLOW_AT))

    def _edit(self, what):
        now = time.monotonic()
        if not self._gesture or self._gesture[0] != what or now - self._gesture[1] > GESTURE_GAP:
            self.seq.snapshot()
        self._gesture = (what, now)

    # ------------------------------------------------------------ keys
    def key_sound(self, n, down):
        """A track key's note, heard straight away (from the MIDI thread on press, the screen's on release)."""
        e = self.e
        if not e or e.slot is None or not 1 <= n <= notes.ROWS:
            return
        pitch = self.seq.shown_notes()[n - 1]
        if down:
            e.note_on(pitch, 100)
        else:
            e.note_off(pitch)

    def lane_key(self, n, down, heard_frame=0, shift=False):
        e = self.e
        if not e or not 1 <= n <= notes.ROWS:
            return
        row = n - 1
        pitch = self.seq.shown_notes()[row]
        if down:
            self.switching[row] = row != self.row and not e.playing    # stopped: a different row's key picks it first
            self.row = row
            self.held[row] = False
            if e.playing:
                # playing: the note goes on where it's playing, and holds for as long as the key does
                self._edit(("live", time.monotonic()))
                i = self.seq.live_place(pitch, heard_frame, e.frames_per_beat())
                self.down[row] = (pitch, i, heard_frame)
                self.held[row] = True
                e.seq_changed()
                self.t.say("%s  STEP %d" % (notes.note_name(pitch), i + 1), 1)
                return
            if self.seq.covering(self.cursor, pitch) is None:
                length = self.seq.pattern.lane_length(pitch)
                if self.cursor >= length:
                    self.t.say("STEP %d IS PAST THE END OF %s (%d STEPS)" % (self.cursor + 1, notes.note_name(pitch),
                                                                           length), 3)
                    return
                self._edit(("toggle", time.monotonic()))
                self.seq.toggle(self.cursor, pitch)
                self.held[row] = True                  # put on now: letting go doesn't take it off
                e.seq_changed()
                self.t.say("%s ON STEP %d" % (notes.note_name(pitch), self.cursor + 1), 1)
            return
        self.key_sound(n, False)
        if row in self.down:
            pitch, i, at = self.down.pop(row)
            steps = round((heard_frame - at) / (e.frames_per_beat() / (self.seq.pattern.steps_per_beat() * self.seq._tf())))
            if steps > 1:
                self.seq.change_note(i, pitch, "length", steps - 1)
                e.seq_changed()
        turned = self.held.pop(row, None)
        switching = self.switching.pop(row, False)
        if turned is None or turned:
            return
        start = self.seq.covering(self.cursor, pitch)
        if start is not None and switching:
            # like the drums: the first press only picks the row; press it again to take the note off
            self.t.say("%s  (PRESS AGAIN TO TAKE THE NOTE OFF)" % notes.note_name(pitch), 2)
            return
        if start is not None:
            self._edit(("toggle", time.monotonic()))
            self.seq.toggle(start, pitch)
            e.seq_changed()
            self.t.say("%s OFF" % notes.note_name(pitch), 1)

    def arrows(self, rows):
        """← / →: the rows an octave (or with SHIFT one row) down / up."""
        low = self.seq.move_rows(rows)
        shown = self.seq.shown_notes()
        self.t.say("NOTES %s - %s" % (notes.note_name(shown[0]), notes.note_name(shown[-1])), 2)
        return low

    def octave(self):
        return len(self.seq.degrees())

    def cycle_mode(self):
        self.mode = (self.mode + 1) % (len(self.pages()) + 1)
        self.t.say("KNOBS: %s%s" % (self.mode_name(), "" if self.mode == 0 else
                                    "  (HOLD A NOTE'S KEY TO LOCK TO IT)"), 3)

    def undo(self):
        n = self.seq.undo()
        if n is None:
            self.t.say("NOTHING TO UNDO", 2)
            return
        self._gesture = None
        self.e.seq_changed()
        self.t.say("UNDONE  (%d MORE)" % len(self.seq.undo_stack), 2)

    # ------------------------------------------------------------ knobs
    def knob(self, number, delta, shift):
        e, seq = self.e, self.seq
        clicks = self.t.knob_clicks(number, delta, shift)
        if number == 1:
            self.cursor = max(0, min(sequencer.MAX_STEPS - 1, self.cursor + clicks))
            if e.playing:
                self._cursor_until = time.monotonic() + 2.0
            return
        if number == 10:
            target = seq.queued if seq.queued is not None else seq.current
            seq.choose_pattern(target + (1 if delta > 0 else -1), e.playing)
            e.seq_changed()
            return
        params = self.params()
        if number - 2 >= len(params):
            return
        param = params[number - 2]
        for row in self.held:
            self.held[row] = True
        step, pitch = self.picked()
        if self.mode == 0:
            if param == "pat_length" and shift:
                # SHIFT + the length knob: the picked row's own length, so it loops on its own cycle
                self._edit((number, "lane", pitch))
                v = seq.change_lane_length(pitch, clicks)
                e.seq_changed()
                own = pitch in seq.pattern.lane_len
                self.t.say("%s  LANE LENGTH %d%s" % (notes.note_name(pitch), v, "" if own else "  (SAME AS THE PATTERN)"), 2)
                return
            if param in ("pat_length", "rate"):
                self._edit((number,))
                v = seq.change_track("length" if param == "pat_length" else "rate", clicks if param == "pat_length" else delta)
                e.seq_changed()
                self.t.say("PATTERN %s  %s" % (LABELS[param], v if param == "pat_length" else sequencer.RATES[v][0]), 2)
                return
            if param in ("root", "scale"):
                if param == "root":
                    seq.set_scale(root=seq.root + (1 if delta > 0 else -1))
                else:
                    seq.set_scale(scale=seq.scale + (1 if delta > 0 else -1))
                e.seq_changed()
                self.t.say("KEY %s %s" % (notes.NAMES[seq.root], notes.SCALES[seq.scale][0]), 2)
                return
            if seq.note(step, pitch) is None:
                self.t.say("NO NOTE: PRESS A TRACK KEY TO PUT ONE ON THE CURSOR'S STEP", 2)
                return
            self._edit((number, step, pitch))
            v = seq.change_note(step, pitch, param, clicks if param in ("length", "vel") else delta)
            e.seq_changed()
            self.t.say("%s  %s  %s" % (notes.note_name(pitch), LABELS[param], self.note_value(param, step, pitch)), 2)
            return
        # a sound page: locked to the picked note while its key is held, else the synth's own sound
        if self.row in self.held and seq.note(step, pitch) is not None:
            self._edit((number, step, pitch, "lock"))
            n = seq.note(step, pitch)
            base = n.locks.get(param, self.d.get_param(param))
            seq.set_lock(step, pitch, param, self.d.stepped(param, base, clicks))
            e.seq_changed()
            v = seq.note(step, pitch).locks[param]
            self.t.say("%s STEP %d  %s  %s  (LOCKED)" % (notes.note_name(pitch), step + 1, self.d.label(param),
                                                         self.d.value_text(param, v)), 2)
            self.audition(step, pitch)
            return
        e.change_drum(param, clicks)
        self.t.say("%s  %s  %s" % (self.d.title, self.d.label(param), self.d.value_text(param)), 2)
        self.audition(None, pitch)

    def note_value(self, param, step, pitch):
        n = self.seq.note(step, pitch)
        if n is None:
            return "-"
        if param == "length":
            return "%d STEP%s" % (n.length, "" if n.length == 1 else "S")
        if param == "vel":
            return str(n.vel)
        if param == "chance":
            return sequencer.CHANCES[n.chance]
        return "x%d" % n.ratchet

    # ------------------------------------------------------------ hearing a setting as you turn it
    def audition(self, step, pitch):
        if self.e.playing:
            return
        now = time.monotonic()
        if self._hear != (step, pitch):
            self._hear, self._heard_at = (step, pitch), 0.0
        self._turned_at = now
        if now - self._heard_at >= HEAR_EVERY:
            self._play_heard(now)
        else:
            self._hear_due = True

    def _play_heard(self, now):
        step, pitch = self._hear
        n = self.seq.note(step, pitch) if step is not None else None
        locks = dict(n.locks) if n else {}
        locks["gate"] = int(self.e.rate * 0.4)
        self.e.audition(pitch, n.vel if n else sequencer.DEFAULT_VELOCITY, locks)
        self._heard_at, self._hear_due = now, False

    def tick(self):
        if not self._hear_due:
            return
        if self.e.playing:
            self._hear_due = False
            return
        now = time.monotonic()
        if now - self._turned_at >= HEAR_AFTER or now - self._heard_at >= HEAR_EVERY:
            self._play_heard(now)

    # ------------------------------------------------------------ drawing
    def knob_boxes(self):
        e, seq = self.e, self.seq
        step, pitch = self.picked()
        n = seq.note(step, pitch)
        shown_pitch = seq.shown_notes()[self.row]
        boxes = [("CURSOR", "STEP %d" % (self.cursor + 1) if self.showing_cursor() else "PLAYING", False)]
        for p in self.params()[:8]:
            if self.mode == 0:
                if p == "pat_length" and self.t.shift_held():
                    boxes.append(("LANE LEN " + notes.note_name(shown_pitch), str(seq.pattern.lane_length(shown_pitch)), False))
                    continue
                if p == "pat_length":
                    v = str(seq.pattern.length)
                elif p == "rate":
                    v = sequencer.RATES[seq.pattern.rate][0]
                elif p == "root":
                    v = notes.NAMES[seq.root]
                elif p == "scale":
                    v = notes.SCALES[seq.scale][0]
                else:
                    v = self.note_value(p, step, pitch)
                boxes.append((LABELS[p], v, False))
            elif n is not None and p in n.locks:
                boxes.append((self.d.label(p), self.d.value_text(p, n.locks[p]), True))
            else:
                boxes.append((self.d.label(p), self.d.value_text(p), False))
        while len(boxes) < 9:
            boxes.append(("", "", False))
        pat = "%d" % (seq.current + 1) + (" > %d" % (seq.queued + 1) if seq.queued is not None else "")
        boxes.append(("PATTERN", pat, False))
        boxes.append(("BIG KNOB", "TAPE", False))
        return boxes

    def draw(self, surf):
        s, e, seq = self.t.s, self.e, self.seq
        self.tick()
        tiny, small = s.font("mono", 600, 11), s.font("mono", 600, 13)
        grey, white, dark, purple = (125, 131, 140), (242, 243, 245), (12, 13, 16), (178, 120, 255)
        green = (60, 203, 127)
        surf.set_clip(None)
        pygame.draw.rect(surf, dark, (0, 36, 1280, 330))
        x, w, gap = 20, 108, 4
        for label, value, locked in self.knob_boxes():
            pygame.draw.rect(surf, (60, 64, 72) if label else (26, 28, 33), (x, 40, w, 38), 1, border_radius=4)
            if label:
                t = tiny.render(label, True, grey)
                surf.blit(t, (x + (w - t.get_width()) // 2, 44))
                v = s.font("mono", 600, 14).render(value, True, green if locked else white)
                surf.blit(v, (x + (w - v.get_width()) // 2, 58))
            x += w + gap
        p = seq.pattern
        info = "KNOBS: %s  (PUSH KNOB 1)   ·   %s  %d STEPS  %s   ·   %s %s   ·   ARROWS: OCTAVE   ·   SHIFT+KNOB 6: LANE LENGTH   ·   SHIFT+CUT: UNDO" % (
            self.mode_name(), self.d.title, p.length, sequencer.RATES[p.rate][0], notes.NAMES[seq.root],
            notes.SCALES[seq.scale][0])
        surf.blit(tiny.render(info, True, grey), (20, 84))
        first = self.first_column()
        x0, pitch_w, cw = 72, 35, 28
        top, row_h = 102, 31
        ch = row_h - 6
        col_x = lambda c: x0 + c * pitch_w
        colour = ui.rgb(self.t.tab_colours.get((e.slot or 0) % 8 + 1) or "#7D838C")
        dim = tuple(round(c * 0.45) for c in colour)
        shown = seq.shown_notes()
        group = sequencer.group_steps(p.steps_per_beat(), tuple(e.time_sig))
        if self.showing_cursor() and first <= self.cursor < first + VISIBLE:
            cx = col_x(self.cursor - first)
            pygame.draw.rect(surf, white, (cx - 4, top - 6, cw + 8, notes.ROWS * row_h + 4), 2, border_radius=6)
        raw = seq.raw_step(e._heard_frame(), e.frames_per_beat()) if e.playing else None
        for r in range(notes.ROWS):
            row = notes.ROWS - 1 - r                     # the lowest note at the bottom
            y = top + r * row_h
            pitch = shown[row]
            lane_len = p.lane_length(pitch)                  # this row's own length, or the pattern's
            playing = (sequencer.phys(raw % (sequencer.live_len(lane_len, seq.trip) or 1), seq.trip)
                       if raw is not None else None)
            root = (pitch - seq.root) % 12 == 0
            tag = colour if root else tuple(round(c * 0.7) for c in colour)
            pygame.draw.rect(surf, tag, (20, y, 46, ch), border_radius=5)
            t = small.render(notes.note_name(pitch), True, dark)
            surf.blit(t, (20 + (46 - t.get_width()) // 2, y + (ch - t.get_height()) // 2))
            if row == self.row:
                pygame.draw.rect(surf, white, (14, y - 4, col_x(VISIBLE - 1) + cw + 6 - 14, ch + 8), 2, border_radius=7)
            for c in range(1, VISIBLE):
                if (first + c) % group == 0 and first + c < lane_len:
                    gx = col_x(c) - (pitch_w - cw + 1) // 2 - 1
                    pygame.draw.line(surf, (88, 94, 104), (gx, y - 2), (gx, y + ch + 1), 2)
            for c in range(VISIBLE):
                i = first + c
                cx = col_x(c)
                if i >= lane_len:
                    if i == lane_len and lane_len != p.length:         # a row with its own length: its end
                        pygame.draw.line(surf, (125, 131, 140), (cx - 3, y), (cx - 3, y + ch), 2)
                else:
                    pygame.draw.rect(surf, (40, 43, 50), (cx, y, cw, ch), 1, border_radius=5)
            # the notes: a bar from its step over its length (clipped to the screen and the pattern)
            for start in range(max(0, first - notes.MAX_LENGTH), min(lane_len, first + VISIBLE)):
                n = p.at(start).get(pitch)
                if n is None:
                    continue
                a, b = max(start, first), min(start + n.length, lane_len, first + VISIBLE)
                if a >= b:
                    continue
                bx, bw = col_x(a - first), col_x(b - first) - col_x(a - first) - (pitch_w - cw)
                shade = tuple(round(d + (c - d) * (0.45 + 0.55 * n.vel / 127)) for c, d in zip(colour, dim))
                pygame.draw.rect(surf, shade, (bx, y, bw, ch), border_radius=5)
                if start >= first:
                    pygame.draw.rect(surf, white, (bx, y, 4, ch), border_top_left_radius=5, border_bottom_left_radius=5)
                if n.locks:
                    pygame.draw.rect(surf, purple, (bx, y, bw, ch), 3, border_radius=5)
            if playing is not None and first <= playing < first + VISIBLE:
                px = col_x(playing - first)
                pygame.draw.rect(surf, white, (px - 2, y - 2, cw + 4, ch + 4), 2, border_radius=6)
        grid_bottom = top + notes.ROWS * row_h
        for c in range(VISIBLE):
            if (first + c) % group == 0:
                t = tiny.render(str(first + c + 1), True, grey)
                surf.blit(t, (col_x(c), grid_bottom - 3))
