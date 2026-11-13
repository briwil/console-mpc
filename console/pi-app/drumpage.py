"""The drum page (the MIDI key), full screen, to Brian's design (Illustrator, Oct 2026):

- the voice's name at the top left, the BPM and the 7 drum keys (the last one played lit) at the top right;
- the settings on the page left to right, one per knob 1-8, over a purple grid:
  - a number is a row of thin lines that are tallest at the setting's value and shrink away from it;
  - a choice (a wave, a filter type, a target...) is a box with its name in it;
  - the setting being turned is lime, with its value in place of its name, until a second after it stops;
- the voice's pages along the bottom (knob 9 turns them), the one showing in red;
- while recording, three red dots under the pages, one filled, stepping left to right.
"""
import math
import time

import pygame

import drumparams
import theme

LEFT, RIGHT = 26, 1247                 # the edges of the rules, grid and pages
PANEL = (76, 115, 1142, 160)           # the black panel the settings sit on
MID_Y = 170                            # the middle of the bars
EDIT_SHOW = 1.0                        # seconds a setting stays lime after its knob stops
TEXT_KINDS = ("menu", "onoff", "voice", "vel_target", "lfo_target")
# The colours, fonts and sizes come from theme.json (and the theme page): see theme.py.


def short_page(name):
    return name.replace("PITCH + VELOCITY", "PITCH+VEL").replace("VELOCITY + CLICK", "VEL+CLICK").replace(" + ", "+")


class DrumPage:
    def __init__(self, transport):
        self.t = transport
        self.edited = {}               # knob number -> when it was last turned
        self._page_size = None
        self._theme_version = None

    def text(self, surf, s, style, colour, x, baseline, align="left", fit=None, size=None):
        """Text in one of the theme's font styles, placed by its baseline. fit: a width it must fit in
        (it gets smaller until it does)."""
        size = size or style["size"]
        tracking = style.get("tracking", 0) or 0
        font = lambda n: self.t.s.font(style["family"], style["weight"], n)
        f = font(size)
        while fit and size > 10 and self.width(f, s, size, tracking) > fit:
            size -= 1
            f = font(size)
        w = self.width(f, s, size, tracking)
        x = x - w if align == "right" else x - w // 2 if align == "centre" else x
        top = baseline - f.get_ascent()
        if not tracking:
            surf.blit(f.render(s, True, colour), (x, top))
            return w
        for i, ch in enumerate(s):
            cx = x + f.size(s[:i])[0] + round(i * tracking * size)
            surf.blit(f.render(ch, True, colour), (cx, top))
        return w

    @staticmethod
    def width(f, s, size, tracking=0.0):
        return f.size(s)[0] + round((len(s) - 1) * tracking * size) if s else 0

    # ------------------------------------------------------------ drawing

    def draw(self, surf):
        th = theme.section("drum_page")
        machine_id = self.t.engine.drums.machine
        if (theme.version(), machine_id) != self._theme_version:
            self._theme_version = (theme.version(), machine_id)
            self._page_size = None
        col = {k: theme.rgb(v) for k, v in th["colours"].items()}
        ink = lambda style, key="colour": theme.rgb(style.get(key, "#FFFFFF"))     # a text style's own colour
        fonts, shp = th["fonts"], th["shapes"]
        t, e = self.t, self.t.engine
        d = e.drums
        surf.set_clip(None)
        surf.fill(col["background"])
        now = time.monotonic()
        voice = t.drum_voice
        pages = t.drum_pages()
        t.drum_tab = min(t.drum_tab, len(pages) - 1)
        _, params = pages[t.drum_tab]

        # top: the voice, the tempo, the machine and its drum keys (with SHIFT, 9-16 on a machine with more)
        self.text(surf, d.names[voice], fonts["voice_name"], ink(fonts["voice_name"]), 22, 45)
        sig = "%d/%d" % tuple(e.time_sig) if getattr(e, "time_sig", None) else "4/4"
        self.text(surf, "%.1f BPM %s" % (e.bpm, sig), fonts["tempo"], ink(fonts["tempo"]), RIGHT, 21, align="right")
        key = max(1, min(d.lanes, getattr(t, "drum_key", voice + 1)))
        bank = (key - 1) // 8
        machine = d.title + ("   KEYS %d-%d" % (bank * 8 + 1, min(d.lanes, bank * 8 + 8)) if d.lanes > 8 else "")
        self.text(surf, machine, fonts["tempo"], ink(fonts["tempo"]), 1040, 46, align="right")
        lane_voice = d.lane_voice
        for k in range(8):
            lane = bank * 8 + k
            if lane >= d.lanes:
                pygame.draw.rect(surf, col["key"], (1052 + k * 25, 30, 20, 20), 1, border_radius=shp["key_corner"])
                continue
            v = lane_voice[lane]
            shared = lane_voice.count(v) > 1
            glow = max(0.0, 1.0 - (now - t._drum_hits[v]) / 0.25) if (not shared or lane + 1 == key) else 0.0
            base = col["key_selected"] if lane + 1 == key else col["key"]
            colour = tuple(round(c + (255 - c) * glow * 0.7) for c in base)
            pygame.draw.rect(surf, colour, (1052 + k * 25, 30, 20, 20), border_radius=shp["key_corner"])

        # the rules and the grid, with the panel on it
        pygame.draw.rect(surf, col["rules"], (LEFT, 57, RIGHT - LEFT, 2))
        pygame.draw.rect(surf, col["rules"], (LEFT, 328, RIGHT - LEFT, 2))
        for k in range(26):
            pygame.draw.rect(surf, col["grid"], (LEFT - 1, 67 + 10 * k, RIGHT - LEFT + 1, 2))
        for k in range(123):
            pygame.draw.rect(surf, col["grid"], (LEFT - 1 + 10 * k, 67, 1, 252))
        pygame.draw.rect(surf, col["panel"], PANEL, border_radius=shp["panel_corner"])

        # the settings, left to right like the knobs
        n = max(1, len(params))
        px, _, pw, _ = PANEL
        box, border = shp["box_size"], shp["box_border"]
        for i, param in enumerate(params):
            cx = round(px + (i + 0.5) * pw / n)
            editing = now - self.edited.get(i + 1, 0.0) < EDIT_SHOW
            colour = col["turning"] if editing else col["setting_bars_and_boxes"]
            kind = d.kind(param)
            if kind in TEXT_KINDS:
                pygame.draw.rect(surf, colour, (cx - box // 2, MID_Y - box // 2, box, box), border,
                                 border_radius=shp["box_corner"])
                self.text(surf, d.value_text(param), fonts["box_text"],
                          col["turning"] if editing else ink(fonts["box_text"]), cx, MID_Y + 8, align="centre",
                          fit=box - 2 * border - 4)
            else:
                self.bar(surf, cx, d.fraction(param), colour, shp)
            label = d.value_text(param) if editing else d.label(param)
            self.text(surf, label, fonts["setting_name"], col["turning"] if editing else ink(fonts["setting_name"]), cx, 258, align="centre", fit=pw / n - 8)

        # the pages along the bottom, spread edge to edge
        style = fonts["pages"]
        size = self.page_size(style)
        labels = [short_page(p[0]) for p in pages]
        f = self.t.s.font(style["family"], style["weight"], size)
        widths = [self.width(f, s, size, style.get("tracking", 0)) for s in labels]
        gap = (RIGHT - LEFT - sum(widths)) / max(1, len(labels) - 1)
        x = LEFT
        for i, s in enumerate(labels):
            self.text(surf, s, style, ink(style, "colour_showing") if i == t.drum_tab else ink(style), round(x), 361,
                      size=size)
            x += widths[i] + gap
        self.text(surf, "KNOB 9: PAGE", fonts["knob_9_hint"], ink(fonts["knob_9_hint"]), RIGHT, 386, align="right")

        # recording: three dots stepping left to right
        if t.recording:
            lit = int(now / 0.3) % 3
            for k in range(3):
                pygame.draw.circle(surf, col["recording_dots"], (624 + k * 16, 381), 6, 0 if k == lit else 2)

    def bar(self, surf, cx, frac, colour, shp):
        """Thin lines, tallest at the value, shrinking with distance from it."""
        lines, pitch, lw = max(2, int(shp["bar_lines"])), shp["bar_line_spacing"], shp["bar_line_width"]
        peak = max(0.0, min(1.0, frac)) * (lines - 1)
        x0 = cx - ((lines - 1) * pitch + lw) // 2
        for k in range(lines):
            h = max(shp["bar_shortest"], shp["bar_tallest"] * math.exp(-abs(k - peak) / max(0.1, shp["bar_falloff"])))
            h = int(round(h / 2)) * 2                     # even, so it sits on whole pixels around the middle
            pygame.draw.rect(surf, colour, (x0 + k * pitch, MID_Y - h // 2, lw, h))

    def page_size(self, style):
        """One size for the page names on every voice: the biggest (up to the theme's) that fits the longest set."""
        if self._page_size is None:
            size = style["size"]
            tr = style.get("tracking", 0)
            d = self.t.engine.drums
            for pages in (d.pages(v) for v in range(d.voices)):
                labels = [short_page(p[0]) for p in pages]
                while size > 10:
                    f = self.t.s.font(style["family"], style["weight"], size)
                    if sum(self.width(f, s, size, tr) for s in labels) + 24 * (len(labels) - 1) <= RIGHT - LEFT:
                        break
                    size -= 1
            self._page_size = size
        return self._page_size
