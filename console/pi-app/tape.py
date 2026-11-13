"""The tape: 8 tracks of audio laid out along a timeline, drawn OP-1 style.

The playhead stays in the middle of the screen and the tape moves past it.
Bar, beat and grid lines are drawn across the lanes, with bar numbers on the
ruler above them.

There's no real audio yet. Each track holds a made-up level for every 1/64
note, and recording writes new made-up levels at the playhead, so the screen
behaves the way it will once the audio engine exists.
"""
import math
import random

import numpy as np
import pygame

import ui
from palette import REGION_COLOURS

RES = 16                    # level values per beat (one per 1/64 note)
TAPE_BARS = 64
TAPE_BEATS = TAPE_BARS * 4          # the tape's length on screen, in beats (a beat is always a quarter note)

# The time signature. Tempo and beats are always in quarter notes; a bar is SIG[0] notes of 1/SIG[1].
SIGNATURES = [(2, 4), (3, 4), (4, 4), (5, 4), (6, 4), (7, 4), (5, 8), (6, 8), (7, 8), (9, 8), (12, 8)]
SIG = (4, 4)
BEATS_PER_BAR = 4.0                 # quarter-note beats in a bar (6/8: 3, 7/8: 3.5)
BEAT_UNIT = 1.0                     # quarter-note beats in one counted beat (x/4: 1, x/8: 0.5)


def set_signature(num, den):
    """Change the time signature (for the whole app: the bar lines, the clock, bar moves, loops)."""
    global SIG, BEATS_PER_BAR, BEAT_UNIT
    if (num, den) not in SIGNATURES:
        num, den = 4, 4
    SIG = (num, den)
    BEAT_UNIT = 4.0 / den
    BEATS_PER_BAR = num * BEAT_UNIT


def signature_text():
    return "%d/%d" % SIG

GRIDS = [("1/4", 1), ("1/8", 2), ("1/16", 4), ("1/32", 8)]     # name, lines per beat
ZOOMS = [16, 8, 4, 2, 1]                                       # bars across the screen

BAR_LINE = (58, 63, 72)
BEAT_LINE = (38, 42, 49)
GRID_LINE = (29, 32, 38)
BEFORE_START = (14, 15, 18)
RULER_TEXT = (125, 131, 140)
RULER_NOW = (242, 243, 245)
LOOP_FILL = (30, 36, 52)
LOOP_FILL_OFF = (24, 26, 31)
LOOP_MARK = (79, 140, 255)
LOOP_MARK_OFF = (70, 76, 88)
SELECT_LINE = (205, 210, 218)      # outline round the box LIFT / CUT would take
SELECTING_LINE = (255, 255, 255)   # while selecting several boxes

# how much of each sample track has something on it, in bars
SAMPLE_FILL = [64, 48, 40, 64, 12, 56, 32, 0]


def sample_track(name, bars):
    """Made-up levels for a track, using the same kind of random envelope as the designer."""
    r = ui._rng(ui._hash(name))
    out = [0.0] * (TAPE_BEATS * RES)
    env, target, run = 0.0, 0.0, 0
    for i in range(min(len(out), bars * BEATS_PER_BAR * RES)):
        if run <= 0:
            on = r() > .28
            run = 10 + math.floor(r() * 60)
            target = .35 + r() * .65 if on else 0
        run -= 1
        env += (target - env) * .18
        out[i] = max(env * (.45 + r() * .55), .04)
    return out


class Tape:
    def __init__(self, screen, engine=None):
        self.s = screen
        self.engine = engine
        if engine:
            self.levels = engine.levels          # real recordings: peak level per 1/64 note
        else:
            self.levels = [np.array(sample_track("track%d" % (n + 1), SAMPLE_FILL[n]), np.float32) for n in range(8)]
        self.pos = 0.0                  # playhead position in beats from the start of the tape
        self.grid = 2                   # index into GRIDS (1/16)
        self.zoom = 2                   # index into ZOOMS (4 bars)
        self.extra_armed = set()        # other armed tracks (1-8), outlined thinly
        self.arm_colour = (125, 131, 140)
        self._rec_env = 0.0
        self._rec_target = 0.0
        self._rec_run = 0
        lane = screen.get("track1_wave") or {"x": 66, "w": 1128}
        self.center = lane["x"] + lane["w"] // 2
        screen.set("playhead", x1=self.center, x2=self.center)
        for n in range(1, 9):
            screen.custom["track%d_lane" % n] = self.draw_lane
            screen.custom["track%d_wave" % n] = self.draw_wave
        screen.custom["ruler"] = self.draw_ruler

    # ------------------------------------------------------------ settings

    @property
    def total_beats(self):
        return self.engine.tape_beats if self.engine else TAPE_BEATS

    @property
    def ppb(self):
        """Pixels per beat at the current zoom."""
        lane = self.s.get("track1_wave")
        width = lane["w"] if lane else 1128
        return width / (ZOOMS[self.zoom] * BEATS_PER_BAR)

    @property
    def step(self):
        """One grid step, in beats."""
        return 1 / GRIDS[self.grid][1]

    def label(self):
        bars = ZOOMS[self.zoom]
        return "GRID %s   %d BAR%s" % (GRIDS[self.grid][0], bars, "" if bars == 1 else "S")

    def cycle_grid(self):
        self.grid = (self.grid + 1) % len(GRIDS)

    def zoom_in(self):
        self.zoom = min(len(ZOOMS) - 1, self.zoom + 1)

    def zoom_out(self):
        self.zoom = max(0, self.zoom - 1)

    def move(self, steps, size):
        """Move by whole steps of `size` beats, landing on the nearest line."""
        n = math.floor(self.pos / size + 1e-3) + steps
        if steps < 0 and abs(self.pos / size - round(self.pos / size)) > 1e-3:
            n += 1          # first step back only goes to the line just behind
        self.pos = min(max(0.0, n * size), self.total_beats)

    # ------------------------------------------------------------ recording (made-up input for now)

    def record(self, track, from_beat, to_beat):
        lv = self.levels[track - 1]
        i0 = max(0, int(from_beat * RES))
        i1 = min(len(lv), int(to_beat * RES))
        for i in range(i0, i1):
            if self._rec_run <= 0:
                self._rec_target = .4 + random.random() * .6 if random.random() > .2 else 0
                self._rec_run = 8 + random.randint(0, 40)
            self._rec_run -= 1
            self._rec_env += (self._rec_target - self._rec_env) * .2
            lv[i] = max(self._rec_env * (.5 + random.random() * .5), .04)

    def level_at(self, track, beat):
        if beat < 0 or beat >= self.total_beats:
            return 0.0
        return self.shape(float(self.levels[track - 1][int(beat * RES)]))

    def shape(self, a):
        """Real audio peaks look tiny drawn as-is; a square root makes quiet parts visible."""
        return min(1.0, math.sqrt(a)) if self.engine else a

    # ------------------------------------------------------------ drawing

    def x_of(self, beat):
        return self.center + (beat - self.pos) * self.ppb

    def beat_of(self, x):
        return self.pos + (x - self.center) / self.ppb

    def lines(self, x0, x1):
        """(x, kind) for every line between x0 and x1; kind is 'bar', 'beat' or 'grid'."""
        ppb = self.ppb
        b0 = max(0.0, self.beat_of(x0))
        b1 = min(float(self.total_beats), self.beat_of(x1))
        found = {}                                  # beat -> kind; bars win over beats over grid lines
        for size, kind in ((self.step, "grid"), (BEAT_UNIT, "beat"), (BEATS_PER_BAR, "bar")):
            if kind != "bar" and size * ppb < 5:
                continue                            # too close together to draw at this zoom
            k = math.ceil(b0 / size - 1e-9)
            while k * size <= b1 + 1e-9:
                found[round(k * size, 6)] = kind
                k += 1
        for beat in sorted(found):
            yield round(self.x_of(beat)), found[beat]

    def draw_lane(self, surf, it):
        self.s.draw_default(surf, it)
        x0, y0, w, h = it["x"], it["y"], it["w"], it["h"]
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(x0, y0, w, h))
        start = round(self.x_of(0))
        if start > x0:
            pygame.draw.rect(surf, BEFORE_START, (x0, y0, start - x0, h), 0, it.get("r", 0))
        loop = self.loop_x()
        if loop:
            lx0, lx1 = max(x0, loop[0]), min(x0 + w, loop[1])
            if lx1 > lx0:
                pygame.draw.rect(surf, LOOP_FILL if loop[2] else LOOP_FILL_OFF, (lx0, y0, lx1 - lx0, h))
        colours = {"bar": BAR_LINE, "beat": BEAT_LINE, "grid": GRID_LINE}
        for x, kind in self.lines(x0, x0 + w):
            pygame.draw.line(surf, colours[kind], (x, y0 + 2), (x, y0 + h - 3), 1)
        self.draw_boxes(surf, it)
        surf.set_clip(clip)
        if int(it["name"][5:it["name"].index("_")]) in self.extra_armed:
            pygame.draw.rect(surf, self.arm_colour, (x0 - 1, y0 - 1, w + 2, h + 2), 1, it.get("r", 0) + 1)

    def visible_regions(self, track, x0, x1):
        """[(x start, x end, colour)] for the boxes on a track that are on screen."""
        e = self.engine
        if not e:
            return []
        fpb = e.frames_per_beat()
        out = []
        for a, b, c in (r[:3] for r in e.regions[track - 1]):
            xa, xb = self.x_of(a / fpb), self.x_of(b / fpb)
            if xb >= x0 and xa <= x1:
                out.append((round(xa), round(xb), ui.rgb(REGION_COLOURS[c % len(REGION_COLOURS)])))
        return out

    def draw_boxes(self, surf, it):
        """Each recording / piece is a rounded box in its own colour, like regions in a DAW."""
        track = int(it["name"][5:it["name"].index("_")])
        y0, h = it["y"] + 1, it["h"] - 2
        for xa, xb, col in self.visible_regions(track, it["x"], it["x"] + it["w"]):
            xa, xb = max(it["x"] - 6, xa + 1), min(it["x"] + it["w"] + 6, xb - 1)    # small gap between touching boxes
            if xb - xa < 1:
                continue
            fill = tuple(int(c * 0.22 + 14) for c in col)
            edge = tuple(int(c * 0.55) for c in col)
            r = min(5, (xb - xa) // 2)
            pygame.draw.rect(surf, fill, (xa, y0, xb - xa, h), 0, r)
            pygame.draw.rect(surf, edge, (xa, y0, xb - xa, h), 1, r)

    def draw_wave(self, surf, it):
        track = int(it["name"][5:it["name"].index("_")])
        e = self.engine
        if e and (track - 1) in e.stereo:
            # a stereo track: left on the top half, right on the bottom, with a thin line between
            top, bottom = dict(it), dict(it)
            half = it["h"] // 2
            top["h"], bottom["y"], bottom["h"] = half, it["y"] + half, it["h"] - half
            self._wave(surf, top, self.levels[track - 1], track)
            self._wave(surf, bottom, self.levels[track - 1 + 8], track)
            pygame.draw.line(surf, (40, 43, 50), (it["x"] + 2, it["y"] + half), (it["x"] + it["w"] - 3, it["y"] + half), 1)
        else:
            self._wave(surf, it, self.levels[track - 1], track)
        self.draw_selection(surf, track)

    def _wave(self, surf, it, lv, track):
        cy = it["y"] + it["h"] / 2
        ppb = self.ppb
        span = max(1, int(3 / ppb * RES))          # level values covered by one 3-pixel column
        x0, x1 = it["x"], it["x"] + it["w"] - 1
        if self.engine:
            parts = [(max(x0, xa + 2), min(x1, xb - 2), col) for xa, xb, col in self.visible_regions(track, x0, x1)]
        else:
            parts = [(x0, x1, ui.rgb(it["c"]))]
        for pa, pb, col in parts:
            start = x0 + ((pa - x0 + 2) // 3) * 3          # keep the 3-pixel columns lined up while scrolling
            for px in range(start, pb, 3):
                beat = self.beat_of(px + 1)
                if beat < 0 or beat >= self.total_beats:
                    continue
                i = int(beat * RES)
                a = float(lv[i:i + span].max()) if span > 1 else float(lv[i])
                if a <= 0.0003:
                    continue
                a = self.shape(a)
                bh = max(1, round(a * (it["h"] - 4)))
                surf.fill(col, (px, round(cy - bh / 2), 2, bh))

    def draw_selection(self, surf, track):
        """An outline round the box(es) that LIFT and CUT would take, on the selected track."""
        lane = self.s.get("track%d_lane" % track)
        if not lane:
            return
        sel = self.selection_x(lane)
        if not sel:
            return
        xa, xb, selecting = sel
        xa, xb = max(lane["x"], xa + 1), min(lane["x"] + lane["w"], xb - 1)
        if xb - xa < 2:
            return
        pygame.draw.rect(surf, SELECTING_LINE if selecting else SELECT_LINE,
                         (xa, lane["y"] + 1, xb - xa, lane["h"] - 2), 2 if selecting else 1, min(5, (xb - xa) // 2))

    def draw_ruler(self, surf, it):
        self.s.draw_default(surf, it)
        font = self.s.font("mono", 500, 11)
        ppb = self.ppb
        bar_px = ppb * BEATS_PER_BAR
        every = 1 if bar_px >= 36 else 2 if bar_px >= 18 else 4
        now_bar = int(self.pos // BEATS_PER_BAR)
        y_bottom = it["y"] + it["h"]
        for x, kind in self.lines(it["x"], it["x"] + it["w"]):
            if kind == "bar":
                bar = round(self.beat_of(x) / BEATS_PER_BAR)
                pygame.draw.line(surf, BAR_LINE, (x, y_bottom - 5), (x, y_bottom - 1), 1)
                if bar % every == 0 and bar < self.total_beats / BEATS_PER_BAR:
                    col = RULER_NOW if bar == now_bar else RULER_TEXT
                    img = font.render(str(bar + 1), True, col)
                    if x + 3 + img.get_width() <= it["x"] + it["w"]:
                        surf.blit(img, (x + 3, it["y"]))
            elif kind == "beat":
                pygame.draw.line(surf, BEAT_LINE, (x, y_bottom - 3), (x, y_bottom - 1), 1)
        loop = self.loop_x()
        if loop:
            col = LOOP_MARK if loop[2] else LOOP_MARK_OFF
            lx0, lx1 = max(it["x"], loop[0]), min(it["x"] + it["w"], loop[1])
            if lx1 > lx0:
                pygame.draw.rect(surf, col, (lx0, y_bottom - 3, lx1 - lx0, 3))
            for x in (loop[0], loop[1]):
                if it["x"] <= x <= it["x"] + it["w"]:
                    pygame.draw.line(surf, col, (x, it["y"]), (x, y_bottom - 1), 2)

    def selection_x(self, it):
        """(x start, x end, selecting) of the selected piece(s) when `it` is the lane of a track LIFT
        would take (the selected one and every other track you hear with a box there), or None."""
        e = self.engine
        if not e or e.recording:
            return None
        sel = e.selection()
        if not sel or it["name"] not in ["track%d_lane" % (t + 1) for t in sel[0]]:
            return None
        fpb = e.frames_per_beat()
        return round(self.x_of(sel[1] / fpb)), round(self.x_of(sel[2] / fpb)), e.sel_anchor is not None

    def loop_x(self):
        """(x start, x end, on) of the loop on screen, or None."""
        e = self.engine
        if not e or not e.loop_region():
            return None
        fpb = e.frames_per_beat()
        return round(self.x_of(e.loop_a / fpb)), round(self.x_of(e.loop_b / fpb)), e.loop_on
