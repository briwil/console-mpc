"""The sequencer page (the MIDI key's second press): the 7 lanes as rows of steps, 32 at a time.

- Knob 1 moves the step cursor (the highlighted column), 1 to 64. It moves along to the 16th column,
  then the steps scroll under it, until step 64 comes on screen and it moves on to the end (and the
  same going back).
- Track keys 1-7 are the drums: press and let go to put a step at the cursor, or take it off. Each one
  plays its sound as you press it. While recording, a press puts the step where it's playing instead,
  on the nearest step.
- Hold a track key and turn knobs 2-9 to change that lane: in STEP mode its length, the velocity,
  chance and ratchets of the step under the cursor, its Euclidean fill and shift, and its rate.
- Push knob 1 for the next mode: the drum's sound pages. There, holding a track key locks the
  setting to the step under the cursor (a parameter lock); with no key held, the knobs change the
  drum's own sound. Stopped, the sound plays as a knob turns (then once a second, and once more
  when it stops).
- Track key 8 undoes (10 steps). Knob 10 picks the pattern.
- Each lane has a box of 8 steps. ← / → move the picked lane's box 8 steps; SHIFT + track key 1-8
  puts that step of the box on (or off) on the picked lane. On a machine with more than 8 drums
  (TR-808, MACHINEDRUM), SHIFT + knob 1 switches the drum keys and the grid between drums 1-8 and 9-16.
"""
import time

import pygame

import drumparams
import sequencer
import ui

HEAR_EVERY = 1.0                 # turning a sound page's knob while stopped plays the sound this often (s)
HEAR_AFTER = 0.5                 # and once more this long after the knob stops
VISIBLE = 32                     # steps on screen at once
FOLLOW_AT = 15                   # the cursor's column (from 0) while the steps scroll under it
STEP_PARAMS = ["length", "vel", "chance", "ratchet", "hits", "rotate", "rate"]       # knobs 2-8 in STEP mode
STEP_LABELS = {"length": "LENGTH", "vel": "VELOCITY", "chance": "CHANCE", "ratchet": "RATCHETS",
               "hits": "EUCLID", "rotate": "SHIFT", "rate": "RATE"}
LANE_PARAMS = ("length", "hits", "rotate", "rate")
CHANCE_SHOW = 1.0                # seconds the steps show chance after the chance knob stops turning
CHANCE_COLOUR = (242, 243, 245)
GESTURE_GAP = 1.5                # seconds: knob turns closer together than this are one undo step
BOX = 8                          # steps in a lane's box (SHIFT + track keys 1-8)
BOX_SHOW = 4.0                   # seconds the grid shows the box after the arrows or SHIFT + a key


class SeqPage:
    def __init__(self, transport):
        self.t = transport
        self.cursor = 0
        self.lane = 0                # the lane picked last (its sound pages are the modes)
        self.mode = 0                # 0: STEP; 1-5: the drum's sound pages
        self.held = {}               # lane -> True once a knob turned while it was held (no toggle on release)
        self._gesture = None         # (what, when): the edit being made, so one turn is one undo step
        self.placed = {}             # lane -> the step a key put down while playing (the knobs edit that one)
        self._cursor_until = 0.0     # while playing, the cursor shows for a moment when knob 1 turns
        self.box = {}                # lane -> the first step of its 8-step box (0, 8, 16...)
        self._box_until = 0.0        # the grid shows the picked lane's box until then
        self._bright_until = 0.0     # the box is drawn at full strength until then (just after the arrows)
        self._hear = None            # (lane, step or None): the sound being turned, to play it while stopped
        self._heard_at = 0.0         # when it last played
        self._turned_at = 0.0        # when its knob last turned
        self._hear_due = False       # turned since it last played

    @property
    def e(self):
        return self.t.engine

    @property
    def seq(self):
        return self.t.engine.seq

    @property
    def d(self):
        return self.t.engine.drums

    def voice(self, lane=None):
        """The drum machine's voice a lane plays (its settings pages)."""
        lv = self.d.lane_voice
        return lv[min(len(lv) - 1, self.lane if lane is None else lane)]

    def short(self, lane):
        names = self.d.lane_short
        return names[lane] if lane < len(names) else "L%d" % (lane + 1)

    def shown_lanes(self):
        """The lanes on screen: up to 8, the bank of the picked lane (9-16 are SHIFT + the drum keys)."""
        n = self.d.lanes
        self.lane = min(self.lane, n - 1)
        first = (self.lane // 8) * 8
        return list(range(first, min(n, first + 8)))

    def pages(self):
        return self.d.pages(self.voice())

    def mode_name(self):
        return "STEP" if self.mode == 0 else self.pages()[self.mode - 1][0]

    def params(self):
        """What knobs 2-9 change in this mode."""
        if self.mode == 0:
            return STEP_PARAMS
        return self.pages()[self.mode - 1][1]

    def box_start(self, lane=None):
        """The first step of a lane's box, kept inside the lane if it got shorter."""
        lane = self.lane if lane is None else lane
        last = (max(1, self.seq.lane(lane).length) - 1) // BOX * BOX
        return min(self.box.get(lane, 0), last)

    def box_text(self, lane=None):
        b = self.box_start(lane)
        return "%d-%d" % (b + 1, b + BOX)

    def bank(self):
        """0: drums 1-8 on the keys and the grid; 1: drums 9-16 (machines with more than 8)."""
        return self.lane // 8

    def move_box(self, way):
        """← / →: the picked lane's box, 8 steps along (it stops at the lane's ends)."""
        if not (self.e and self.e.drums):
            return
        last = (max(1, self.seq.lane(self.lane).length) - 1) // BOX * BOX
        self.box[self.lane] = max(0, min(last, self.box_start() + way * BOX))
        self._box_until = time.monotonic() + BOX_SHOW
        self._bright_until = time.monotonic() + 1.0
        self.t.say("%s  BOX: STEPS %s  (SHIFT + KEYS 1-8)" % (self.short(self.lane), self.box_text()), 2)

    def box_key(self, n):
        """SHIFT + track key n: the box's nth step on the picked lane, on or off."""
        lane = self.lane
        i = self.box_start() + n - 1
        self._box_until = time.monotonic() + BOX_SHOW
        length = self.seq.lane(lane).length
        if i >= length:
            self.t.say("STEP %d IS PAST THE END OF %s (%d STEPS)" % (i + 1, self.short(lane), length), 3)
            return
        self._edit(("toggle", time.monotonic()))
        on = self.seq.toggle(lane, i)
        self.e.seq_changed()
        self.t.say("%s  STEP %d %s" % (self.short(lane), i + 1, "ON" if on else "OFF"), 1)

    def showing_cursor(self):
        """The blue cursor: always when stopped; while playing, only just after knob 1 turns."""
        return not self.e.playing or time.monotonic() < self._cursor_until

    def target(self, lane):
        """The step the knobs work on: while playing, the one the key just put down, else the cursor."""
        if self.e.playing and not self.showing_cursor() and self.placed.get(lane) is not None:
            return self.placed[lane]
        return self.cursor

    def first_column(self):
        """The first step on screen: following the cursor, or while playing the picked lane's playhead."""
        at = self.cursor
        if time.monotonic() < self._box_until:
            return min(sequencer.MAX_STEPS - VISIBLE, self.box_start() // VISIBLE * VISIBLE)
        if self.e.playing and not self.showing_cursor():
            at = self.seq.position(self.e._heard_frame(), self.e.frames_per_beat())[self.lane]
        return max(0, min(sequencer.MAX_STEPS - VISIBLE, at - FOLLOW_AT))

    def _edit(self, what):
        """Before changing the pattern: one undo step per key press, or per run of turns of one knob."""
        now = time.monotonic()
        if not self._gesture or self._gesture[0] != what or now - self._gesture[1] > GESTURE_GAP:
            self.seq.snapshot()
        self._gesture = (what, now)

    # ------------------------------------------------------------ keys and knobs

    def lane_key(self, n, down, heard_frame=0, shift=False):
        """Drum key n pressed or let go (with SHIFT: the nth step of the picked lane's box)."""
        e = self.e
        if not e or not e.drums:
            return
        if shift:
            if down:
                self.box_key(n)
            return
        lane = n - 1 + 8 * self.bank()
        if lane >= self.d.lanes:
            return
        if down:
            # stopped: pressing a different drum's key picks its lane; press it again for a step
            self._switching = lane != self.lane and not e.playing
            self.lane = lane
            self.t.drum_voice = self.voice()
            self.mode = min(self.mode, len(self.pages()))
            self.held[lane] = False
            if e.playing:
                # playing: the step goes where it's playing (the nearest step), not at the cursor
                self._edit(("live", time.monotonic()))
                i = self.seq.live_place(lane, heard_frame, e.frames_per_beat())
                self.placed[lane] = i
                self._cursor_until = 0.0
                self.held[lane] = True                     # placed already: letting go doesn't toggle
                e.seq_changed()
                self.t.say("%s  STEP %d" % (self.short(lane), i + 1), 1)
            return
        turned = self.held.pop(lane, None)
        if turned is None or turned:
            return
        if getattr(self, "_switching", False):
            self._switching = False
            self.t.say("%s  (PRESS AGAIN TO ADD A STEP)" % self.d.lane_names[lane], 2)
            return
        length = self.seq.lane(lane).length
        if self.cursor >= length:
            self.t.say("STEP %d IS PAST THE END OF %s (%d STEPS)" % (self.cursor + 1, self.short(lane), length), 3)
            return
        self._edit(("toggle", time.monotonic()))
        on = self.seq.toggle(lane, self.cursor)
        e.seq_changed()
        self.t.say("%s  STEP %d %s" % (self.short(lane), self.cursor + 1, "ON" if on else "OFF"), 1)

    def cycle_mode(self):
        self.mode = (self.mode + 1) % (len(self.pages()) + 1)
        self.t.say("KNOBS: %s%s" % (self.mode_name(), "" if self.mode == 0 else
                                    "  (HOLD A DRUM KEY TO LOCK TO THE STEP)"), 3)

    def undo(self):
        n = self.seq.undo()
        if n is None:
            self.t.say("NOTHING TO UNDO", 2)
            return
        self._gesture = None
        self.e.seq_changed()
        left = len(self.seq.undo_stack)
        self.t.say("UNDONE%s  (%d MORE)" % ("" if n == self.seq.current else " IN PATTERN %d" % (n + 1), left), 2)

    def knob(self, number, delta, shift):
        e, seq = self.e, self.seq
        clicks = self.t.knob_clicks(number, delta, shift)
        if number == 1 and shift and self.d.lanes > 8:
            # SHIFT + knob 1 with more than 8 drums (TR-808, MACHINEDRUM): the keys and grid go 1-8 / 9-16
            bank = 1 if delta > 0 else 0
            if bank != self.bank():
                self.lane = min(self.d.lanes - 1, bank * 8 + self.lane % 8)
                self.t.drum_voice = self.voice()
                self.mode = min(self.mode, len(self.pages()))
                self.held, self.placed = {}, {}
            self.t.say("DRUM KEYS: %s" % ("9-16" if self.bank() else "1-8"), 2)
            return
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
        lanes = sorted(self.held)
        if self.mode == 0:
            # the held drum keys' lanes, or with none held the lane picked last
            held = bool(lanes)
            lanes = lanes or [self.lane]
            self._edit((number, tuple(lanes)))
            for lane in lanes:
                if held:
                    self.held[lane] = True
                i = self.target(lane)
                if param in LANE_PARAMS:
                    seq.change_lane(lane, param, clicks if param == "length" else delta)
                elif i >= seq.lane(lane).length:
                    self.t.say("STEP %d IS PAST THE END OF %s" % (i + 1, self.short(lane)), 2)
                    return
                elif held or seq.step(lane, i).on:          # with no key held, only a step that's on
                    seq.change_step(lane, i, param, clicks if param == "vel" else delta)
                else:
                    self.t.say("STEP %d OF %s IS OFF: HOLD ITS KEY TO SET IT" % (i + 1, self.short(lane)), 2)
                    return
            e.seq_changed()
            if param == "chance":
                self._chance_until = time.monotonic() + CHANCE_SHOW   # the steps show chance for a moment
            lane = lanes[-1]
            self.t.say("%s  %s  %s" % (self.short(lane), STEP_LABELS[param], self.step_value(param, lane)), 2)
            return
        # a sound page: lock it to the step under the cursor while a drum key is held, else the drum's sound
        if self.lane in self.held:
            lane = self.lane
            if not e.drums.lockable(param):
                self.t.say("%s CAN'T BE LOCKED TO A STEP" % e.drums.label(param), 3)
                return
            i = self.target(lane)
            if i >= seq.lane(lane).length:
                self.t.say("STEP %d IS PAST THE END OF %s" % (i + 1, self.short(lane)), 3)
                return
            self._edit((number, lane, "lock"))
            self.held[lane] = True
            st = seq.step(lane, i)
            base = st.locks.get(param, e.drums.get_param(param))
            seq.set_lock(lane, i, param, e.drums.stepped(param, base, clicks))
            e.seq_changed()
            v = seq.step(lane, i).locks[param]
            self.audition(lane, i)
            self.t.say("%s STEP %d  %s  %s  (LOCKED)" % (self.short(lane), i + 1, e.drums.label(param),
                                                         e.drums.value_text(param, v)), 2)
            return
        e.change_drum(param, clicks)
        self.audition(self.lane, None)
        self.t.say("%s  %s  %s" % (self.short(self.lane), e.drums.label(param), e.drums.value_text(param)), 2)

    def audition(self, lane, step):
        """A sound page's knob turned while stopped: play the sound (a locked step as the step plays, with
        its velocity and locks) now, then at most once a second while it keeps turning, and once more
        when it stops."""
        if self.e.playing:
            return
        now = time.monotonic()
        if self._hear != (lane, step):
            self._hear, self._heard_at = (lane, step), 0.0
        self._turned_at = now
        if now - self._heard_at >= HEAR_EVERY:
            self._play_heard(now)
        else:
            self._hear_due = True

    def _play_heard(self, now):
        lane, step = self._hear
        if step is None:
            self.e.audition(lane, sequencer.DEFAULT_VELOCITY)
        else:
            st = self.seq.step(lane, step)
            self.e.audition(lane, st.vel, st.locks)
        self._heard_at, self._hear_due = now, False

    def tick(self):
        """Every frame: the last turn's sound, once the knob has stopped (or a second has gone by)."""
        if not self._hear_due:
            return
        if self.e.playing:
            self._hear_due = False
            return
        now = time.monotonic()
        if now - self._turned_at >= HEAR_AFTER or now - self._heard_at >= HEAR_EVERY:
            self._play_heard(now)

    # ------------------------------------------------------------ values for the screen

    def step_value(self, param, lane=None):
        lane = self.lane if lane is None else lane
        ln = self.seq.lane(lane)
        if param == "length":
            return str(ln.length)
        if param == "hits":
            return "OFF" if not ln.hits else "%d/%d" % (ln.hits, ln.length)
        if param == "rotate":
            return str(ln.rotate)
        if param == "rate":
            return sequencer.RATES[ln.rate][0]
        i = self.target(lane)
        if i >= ln.length:
            return "-"
        st = ln.steps[i]
        if param == "vel":
            return str(st.vel)
        if param == "chance":
            return sequencer.CHANCES[st.chance]
        return "x%d" % st.ratchet

    def knob_boxes(self):
        """[(label, value, locked)] for knobs 1-9, then 10 and the big knob."""
        e = self.e
        i = self.target(self.lane)
        if self.showing_cursor():
            boxes = [("CURSOR", "STEP %d" % (self.cursor + 1), False)]
        else:
            boxes = [("CURSOR", "PLAYING" if self.placed.get(self.lane) is None else "STEP %d" % (i + 1), False)]
        params = self.params()
        st = None
        ln = self.seq.lane(self.lane)
        if i < ln.length:
            st = ln.steps[i]
        for i in range(8):
            if i >= len(params):
                boxes.append(("", "", False))
                continue
            p = params[i]
            if self.mode == 0:
                boxes.append((STEP_LABELS[p], self.step_value(p), False))
            elif st is not None and p in st.locks:
                boxes.append((e.drums.label(p), e.drums.value_text(p, st.locks[p]), True))
            else:
                boxes.append((e.drums.label(p), e.drums.value_text(p), False))
        pat = "%d" % (self.seq.current + 1) + (" > %d" % (self.seq.queued + 1) if self.seq.queued is not None else "")
        boxes.append(("PATTERN", pat, False))
        boxes.append(("BIG KNOB", "TAPE", False))
        return boxes

    # ------------------------------------------------------------ drawing

    def draw(self, surf):
        s, e, seq = self.t.s, self.e, self.seq
        self.tick()
        tiny, small, mid = s.font("mono", 600, 11), s.font("mono", 600, 14), s.font("mono", 700, 15)
        grey, white, dark, purple = (125, 131, 140), (242, 243, 245), (12, 13, 16), (178, 120, 255)
        green, cursor_col = (60, 203, 127), (28, 78, 86)
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, 36, 1280, 330))
        # what each knob does, with its value (green: locked to the step under the cursor)
        x, w, gap = 20, 108, 4
        for n, (label, value, locked) in enumerate(self.knob_boxes()):
            pygame.draw.rect(surf, (60, 64, 72) if label else (26, 28, 33), (x, 40, w, 38), 1, border_radius=4)
            if label:
                t = tiny.render(label, True, grey)
                surf.blit(t, (x + (w - t.get_width()) // 2, 44))
                v = small.render(value, True, green if locked else white)
                surf.blit(v, (x + (w - v.get_width()) // 2, 58))
            x += w + gap
        ln = seq.lane(self.lane)
        info = "KNOBS: %s  (PUSH KNOB 1)   ·   %s  %d STEPS  %s   ·   %s  ·   SHIFT+CUT: UNDO" % (
            self.mode_name(), self.short(self.lane), ln.length, sequencer.RATES[ln.rate][0], self.d.title)
        info += "   ·   ARROWS: BOX %s   ·   SHIFT+KEY: STEP" % self.box_text()
        if self.d.lanes > 8:
            info += "   ·   SHIFT+KNOB 1: %s" % ("DRUMS 1-8" if self.lane >= 8 else "DRUMS 9-16")
        surf.blit(tiny.render(info, True, grey), (20, 84))
        # the grid
        first = self.first_column()
        x0, pitch, cw = 72, 35, 28
        shown = self.shown_lanes()
        top, row_h = 102, (35 if len(shown) <= 7 else 31)
        ch = row_h - 6
        col_x = lambda c: x0 + c * pitch
        grid_bottom = top + len(shown) * row_h
        sig = tuple(e.time_sig)
        groups = {l: sequencer.group_steps(seq.lane(l).steps_per_beat(), sig) for l in shown}
        # the picked lane's 8-step box: a block in the lane's colour under its steps, drawn first so the
        # cursor column and the steps go on top. A third strength normally; full while SHIFT is held and
        # for a second after the arrows move it (then the steps inside are drawn dark)
        box = None
        bright = self.t.shift_held() or time.monotonic() < self._bright_until
        if self.lane in shown:
            b = self.box_start()
            c0, c1 = max(b, first), min(b + BOX, first + VISIBLE, seq.lane(self.lane).length)
            if c0 < c1:
                y = top + shown.index(self.lane) * row_h
                bx = col_x(c0 - first)
                rect = (bx - 4, y - 4, col_x(c1 - first) - bx + 8 - (pitch - cw), ch + 8)
                full = ui.rgb(self.t.tab_colours.get(self.lane % 8 + 1) or "#7D838C")
                bg = (12, 13, 16)
                fill = full if bright else tuple(round(b + (c - b) * 0.33) for c, b in zip(full, bg))
                pygame.draw.rect(surf, fill, rect, border_radius=7)
                box = (b, b + BOX)
        if self.showing_cursor() and first <= self.cursor < first + VISIBLE:
            cx = col_x(self.cursor - first)
            # the cursor: a white outline down the column (like the picked lane's outline across)
            pygame.draw.rect(surf, white, (cx - 4, top - 6, cw + 8, len(shown) * row_h + 4), 2, border_radius=6)
        playing = None
        if e.playing:
            playing = seq.position(e._heard_frame(), e.frames_per_beat())
        now = time.monotonic()
        show_chance = now < getattr(self, "_chance_until", 0.0)
        for row, lane in enumerate(shown):
            y = top + row * row_h
            colour = lane_colour = ui.rgb(self.t.tab_colours.get(lane % 8 + 1) or "#7D838C")
            dim = lane_dim = tuple(round(c * 0.75) for c in colour)
            # the drum's tag, lit for a moment when it plays
            hit = max(self.t._drum_hits[self.voice(lane)],
                      e.seq_hits[lane] if e.seq_hits[lane] <= now else 0.0)
            glow = max(0.0, 1.0 - (now - hit) / 0.2)
            tag = tuple(round(c + (255 - c) * glow * 0.6) for c in colour)
            pygame.draw.rect(surf, tag, (20, y, 42, ch), border_radius=5)
            t = small.render(self.short(lane), True, dark)
            surf.blit(t, (20 + (42 - t.get_width()) // 2, y + (ch - t.get_height()) // 2))
            if lane == self.lane:
                pygame.draw.rect(surf, white, (14, y - 4, col_x(VISIBLE - 1) + cw + 6 - 14, ch + 8), 2, border_radius=7)
            lane_steps = seq.lane(lane)
            # a grey line between the lane's beats: every 4 steps at 1/16, 3 at 1/8T, by its time signature
            for c in range(1, VISIBLE):
                if (first + c) % groups[lane] == 0 and first + c < lane_steps.length:
                    gx = col_x(c) - (pitch - cw + 1) // 2 - 1
                    pygame.draw.line(surf, (88, 94, 104), (gx, y - 2), (gx, y + ch + 1), 2)
            for c in range(VISIBLE):
                i = first + c
                x = col_x(c)
                st = lane_steps.steps[i]
                if i >= lane_steps.length:
                    pygame.draw.rect(surf, (32, 34, 40), (x, y, cw, ch), 1, border_radius=5)
                    continue
                in_box = bright and box is not None and lane == self.lane and box[0] <= i < box[1]
                colour, dim = (dark, dark) if in_box else (lane_colour, lane_dim)
                if st.on:
                    # filled from the bottom by its velocity (or, just after turning the chance knob, its chance)
                    c = sequencer.CHANCES[st.chance]
                    if show_chance and ":" in c:
                        t = tiny.render(c, True, CHANCE_COLOUR)
                        surf.blit(t, (x + (cw - t.get_width()) // 2, y + (ch - t.get_height()) // 2))
                    else:
                        frac = int(c[:-1]) / 100 if show_chance else st.vel / 127
                        h = max(2, round(ch * frac))
                        pygame.draw.rect(surf, CHANCE_COLOUR if show_chance else colour, (x, y + ch - h, cw, h),
                                         border_bottom_left_radius=5, border_bottom_right_radius=5,
                                         border_top_left_radius=5 if h >= ch - 1 else 0,
                                         border_top_right_radius=5 if h >= ch - 1 else 0)
                    if not st.locks:
                        pygame.draw.rect(surf, colour, (x, y, cw, ch), 2, border_radius=5)
                if st.locks:
                    pygame.draw.rect(surf, purple, (x, y, cw, ch), 3, border_radius=5)
                elif not st.on:
                    pygame.draw.rect(surf, dim, (x, y, cw, ch), 1, border_radius=5)
                if playing is not None and playing[lane] == i:
                    pygame.draw.rect(surf, white, (x - 2, y - 2, cw + 4, ch + 4), 2, border_radius=6)
        # step numbers along the bottom, every 4
        g = groups[self.lane]                                   # numbered by the picked lane's beats
        for c in range(VISIBLE):
            if (first + c) % g == 0:
                t = tiny.render(str(first + c + 1), True, grey)
                surf.blit(t, (col_x(c), grid_bottom - 3))
