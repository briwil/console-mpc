"""Track focus view: one track grows to fill most of the screen and the others slide away.

Below the big track sits a panel with a reel-to-reel tape animation and the
track's details. Pressing the track's key again slides everything back.

It works by moving the layout's own items (track tabs, numbers, lanes,
waveforms and meters), so a layout made in the Screen Designer keeps working.
"""
import math

import pygame

import ui

TRACK_PARTS = ("tab", "num", "lane", "wave", "meter")
PANEL_H = 96              # height of the reel panel under the focused track
GAP = 6
LABEL_H = 38             # the knob labels' strip above the big track (knobs 1-8 sit above the screen)
SLIDE_SECONDS = 0.28


def ease(f):
    return f * f * (3 - 2 * f)            # smoothstep: starts and ends gently


class Focus:
    def __init__(self, screen, tape_view):
        self.s = screen
        self.tape = tape_view
        self.track = None                 # the focused track, 1-8, or None
        self.shown = 1                    # which track the animation is showing
        self.f = 0.0                      # 0 = all 8 tracks, 1 = focused
        self.angle = [0.0, 0.0]           # reel rotation
        self.info = {}                    # text for the panel, filled in by the app
        self.home = {}                    # each part's position in the layout
        for n in range(1, 9):
            for part in TRACK_PARTS:
                it = screen.get("track%d_%s" % (n, part))
                if it:
                    self.home[(n, part)] = dict(it)
        first, last = screen.get("track1_lane"), screen.get("track8_lane")
        self.ok = bool(first and last)
        if not self.ok:
            return
        self.top = first["y"]
        self.bottom = last["y"] + last["h"]
        # clip track parts to the lanes area, so sliding tracks never draw over the header or footer
        for n in range(1, 9):
            for part in TRACK_PARTS:
                name = "track%d_%s" % (n, part)
                if screen.get(name):
                    screen.custom[name] = self._clipped(screen.custom.get(name))
        screen.after["track8_meter"] = self.draw_panel

    @property
    def active(self):
        return self.f > 0.001

    def toggle(self, track):
        if self.track is None:
            self.track = self.shown = track
        elif self.track == track:
            self.track = None
        else:
            self.track = self.shown = track

    def _clipped(self, draw):
        def fn(surf, it):
            if not self.active:
                (draw or self.s.draw_default)(surf, it)
                return
            old = surf.get_clip()
            surf.set_clip(pygame.Rect(0, self.top - 2, ui.WIDTH, self.bottom - self.top + 4))
            (draw or self.s.draw_default)(surf, it)
            surf.set_clip(old)
        return fn

    # ------------------------------------------------------------ every frame

    def update(self, seconds, playing, speed=1.0):
        if not self.ok:
            return
        target = 1.0 if self.track else 0.0
        step = seconds / SLIDE_SECONDS
        self.f = min(target, self.f + step) if target > self.f else max(target, self.f - step)
        # reels turn while the tape moves; the emptier reel turns faster, like real tape
        if playing:
            p = self.progress()
            for i, fill in enumerate((1 - p, p)):
                r = 0.45 + 0.55 * math.sqrt(max(0.0, fill))
                self.angle[i] -= seconds * speed * 2.4 / r
        self.layout(ease(self.f))

    def progress(self):
        total = self.tape.total_beats
        return min(1.0, max(0.0, self.tape.pos / total)) if total else 0.0

    def layout(self, e):
        n0 = self.shown
        span = self.bottom - self.top
        lane_h = span - PANEL_H - GAP - LABEL_H
        home_lane = self.home.get((n0, "lane"))
        for (n, part), h in self.home.items():
            if e <= 0:
                self.s.set("track%d_%s" % (n, part), **{k: h[k] for k in ("x", "y", "w", "h") if k in h})
                continue
            if n == n0 and home_lane:
                # grow the focused track from its own lane to the big lane
                y0 = home_lane["y"]
                ny = y0 + (self.top + LABEL_H - y0) * e
                nh = home_lane["h"] + (lane_h - home_lane["h"]) * e
                if part in ("lane", "wave"):
                    inset = h["y"] - y0
                    self.s.set("track%d_%s" % (n, part), y=round(ny + inset),
                               h=round(nh - 2 * inset if part == "wave" else nh))
                else:
                    offset = h["y"] - y0                     # tabs, numbers, meters keep their place in the lane
                    self.s.set("track%d_%s" % (n, part), y=round(ny + offset))
            else:
                # the others slide away: above the focused track go up, below go down
                d = -1 if n < n0 else 1
                self.s.set("track%d_%s" % (n, part), y=round(h["y"] + d * span * 1.05 * e))

    # ------------------------------------------------------------ the reel panel

    def draw_panel(self, surf):
        if not self.active or not self.ok:
            return
        e = ease(self.f)
        y = round(self.bottom - PANEL_H + (PANEL_H + 20) * (1 - e))     # slides up from below
        lane = self.home.get((self.shown, "lane"))
        x0, x1 = (lane["x"], lane["x"] + lane["w"]) if lane else (60, 1200)
        old = surf.get_clip()
        surf.set_clip(pygame.Rect(0, self.top, ui.WIDTH, self.bottom - self.top))
        self.draw_knob_labels(surf, e)
        pygame.draw.rect(surf, (20, 22, 26), (x0, y, x1 - x0, PANEL_H), 0, 6)

        colour = ui.rgb((self.home.get((self.shown, "tab")) or {}).get("c", "#F2F3F5"))
        dark = tuple(int(c * 0.35) for c in colour)
        cy = y + PANEL_H // 2
        r_max = PANEL_H // 2 - 8
        p = self.progress()
        centres = (x0 + 70, x0 + 250)
        packs = (1 - p, p)
        # the tape running between the reels, under a little tape head
        head_x = (centres[0] + centres[1]) // 2
        r_pack = [round(r_max * (0.45 + 0.55 * math.sqrt(max(0.0, f)))) for f in packs]
        pygame.draw.line(surf, (90, 70, 50), (centres[0], cy + r_pack[0]), (head_x, cy + r_max + 2), 2)
        pygame.draw.line(surf, (90, 70, 50), (head_x, cy + r_max + 2), (centres[1], cy + r_pack[1]), 2)
        pygame.draw.rect(surf, (125, 131, 140), (head_x - 9, cy + r_max - 4, 18, 9), 0, 2)
        for i, (cx, r) in enumerate(zip(centres, r_pack)):
            pygame.draw.circle(surf, (38, 41, 48), (cx, cy), r_max)            # reel flange
            pygame.draw.circle(surf, (64, 48, 36), (cx, cy), r)                # tape wound on it
            pygame.draw.circle(surf, dark, (cx, cy), round(r_max * 0.42))      # hub
            for k in range(3):                                                # spokes
                a = self.angle[i] + k * 2 * math.pi / 3
                ex, ey = cx + math.cos(a) * r_max * 0.38, cy + math.sin(a) * r_max * 0.38
                pygame.draw.line(surf, colour, (cx, cy), (round(ex), round(ey)), 4)
            pygame.draw.circle(surf, (20, 22, 26), (cx, cy), 5)

        # details on the right
        tx = centres[1] + r_max + 40
        big = self.s.font("mono", 600, 22)
        small = self.s.font("mono", 500, 15)
        title = big.render("TRACK %d" % self.shown, True, colour)
        surf.blit(title, (tx, y + 12))
        lines = self.info.get("lines", [])
        if len(lines) > 4:                       # the box under the playhead: knobs 4-6 change it
            surf.blit(small.render(lines[4], True, (242, 243, 245)), (tx + title.get_width() + 24, y + 18))
        for i, text in enumerate(lines[:4]):
            col = (242, 243, 245) if i == 0 else (125, 131, 140)
            x = tx if i < 2 else tx + 330            # two columns of two lines
            surf.blit(small.render(text, True, col), (x, y + 46 + (i % 2) * 20))
        surf.set_clip(old)

    def draw_knob_labels(self, surf, e):
        """Eight labels along the top, one above each knob: what it does, and its value below.
        The app fills self.info["knobs"] with eight (name, value, active) triples.
        They appear once the track has mostly grown (no half-faded text while it slides)."""
        knobs = self.info.get("knobs")
        if not knobs or e < 0.6:
            return
        name_font, val_font = self.s.font("mono", 600, 13), self.s.font("mono", 500, 13)
        colw = ui.WIDTH / len(knobs)
        top = self.top
        for i, (name, value, active) in enumerate(knobs):
            cx = round((i + 0.5) * colw)
            if i:
                x = round(i * colw)
                pygame.draw.line(surf, (40, 43, 50), (x, top + 3), (x, top + LABEL_H - 3), 1)
            a = (242, 243, 245) if active else (80, 85, 92)
            b = (125, 131, 140) if active else (62, 66, 72)
            while len(value) > 1 and val_font.size(value)[0] > colw - 12:
                value = value[:-1]                       # too long for its column: cut the end
            n = name_font.render(name, True, a)
            v = val_font.render(value, True, b)
            surf.blit(n, (cx - n.get_width() // 2, top + 2))
            surf.blit(v, (cx - v.get_width() // 2, top + 18))
